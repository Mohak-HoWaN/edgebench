import { useState } from "react";
import { toast } from "sonner";
import { Field, NativeSelect } from "@/components/Field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDatasets } from "@/lib/datasets";
import { useAddInt8, type ModelInfo } from "@/lib/models";

const OPS = [
  ["openvino_int8", "OpenVINO INT8 (NNCF)"],
  ["onnx_int8", "ONNX INT8 (static, detect head kept in float)"],
] as const;
export const MIN_CALIBRATION = 50;

/**
 * An INT8 conversion learns the value ranges from real pictures. It needs at least 50, picked as a seeded mix of the
 * dataset's capture sources, and the accuracy check against the PyTorch baseline is what tells you whether it is still good.
 */
export function AddInt8({ model }: { model: ModelInfo }) {
  const add = useAddInt8();
  const datasets = useDatasets();
  const usable = (datasets.data ?? []).filter((d) => d.head !== null);
  const [op, setOp] = useState<string>("openvino_int8");
  const [datasetPick, setDatasetPick] = useState<number | null>(null);
  const [count, setCount] = useState(200);
  const dataset = usable.find((d) => d.id === (datasetPick ?? usable[0]?.id));
  const enough = dataset !== undefined && (dataset.head?.image_count ?? 0) >= MIN_CALIBRATION;
  const countOk = Number.isInteger(count) && count >= MIN_CALIBRATION && count <= 5000;
  const problem =
    dataset === undefined
      ? "Add a dataset first: the quantizer learns from its pictures."
      : !enough
        ? `${dataset.name} has ${String(dataset.head?.image_count ?? 0)} pictures; INT8 calibration needs at least ${String(MIN_CALIBRATION)}. One picture repeated gave a worse model than 128 different ones.`
        : !countOk
          ? `Use between ${String(MIN_CALIBRATION)} and 5000 pictures.`
          : null;

  return (
    <form
      className="max-w-prose space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        if (problem !== null || dataset === undefined) return;
        add.mutate(
          { id: model.id, op, dataset_id: dataset.id, count },
          {
            onSuccess: () => {
              toast.success(
                "The INT8 conversion was added; it also builds the ONNX FP32 file it needs",
              );
            },
            onError: (err) => {
              toast.error(err.message);
            },
          },
        );
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="INT8 format">
          {(id) => (
            <NativeSelect
              id={id}
              value={op}
              onChange={(e) => {
                setOp(e.target.value);
              }}
            >
              {OPS.map(([value, label]) => (
                <option key={value} value={value}>
                  {label}
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
        <Field
          label="Calibrate on dataset"
          help="The newest version of this dataset. Pictures are picked as a seeded mix of the capture sources, so the same choice always gives the same subset."
        >
          {(id, describedBy) => (
            <NativeSelect
              id={id}
              aria-describedby={describedBy}
              value={dataset?.id ?? ""}
              onChange={(e) => {
                setDatasetPick(Number(e.target.value));
              }}
            >
              {usable.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.head?.image_count ?? 0} pictures)
                </option>
              ))}
            </NativeSelect>
          )}
        </Field>
        <Field
          label="Calibration pictures"
          help={`At least ${String(MIN_CALIBRATION)}. More pictures take longer to convert and rarely help beyond a few hundred.`}
        >
          {(id, describedBy) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              type="number"
              inputMode="numeric"
              min={MIN_CALIBRATION}
              max={5000}
              value={count}
              aria-invalid={!countOk}
              onChange={(e) => {
                setCount(Number(e.target.value));
              }}
            />
          )}
        </Field>
      </div>
      <p className="text-sm text-muted-foreground">
        Built from the ONNX FP32 export at {String(model.imgsz ?? 640)} px, which is added too if it
        is missing. To see whether it is still accurate, put it in an experiment with the PyTorch
        baseline.
      </p>
      {problem ? (
        <p role="status" className="border-l-2 border-warn pl-3 text-sm">
          {problem}
        </p>
      ) : null}
      <Button type="submit" disabled={problem !== null || add.isPending}>
        Add this INT8 conversion
      </Button>
    </form>
  );
}
