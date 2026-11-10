import { useState } from "react";
import { toast } from "sonner";
import { Field, NativeSelect } from "@/components/Field";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useAddVariant, type ModelInfo } from "@/lib/models";

const OPS = [
  ["onnx_fp32", "ONNX FP32"],
  ["onnx_fp16", "ONNX FP16"],
  ["torchscript", "TorchScript FP32"],
  ["openvino_fp32", "OpenVINO FP32"],
  ["openvino_fp16", "OpenVINO FP16"],
  ["ncnn_fp32", "ncnn FP32"],
  ["ncnn_fp16", "ncnn FP16"],
] as const;
const SIZES = [320, 416, 480, 512, 640, 800, 960, 1280];

/** Build a conversion the default grid does not have: another input size, or an ONNX export left unsimplified. */
export function AddVariant({ model }: { model: ModelInfo }) {
  const add = useAddVariant();
  const [op, setOp] = useState<string>("onnx_fp32");
  const [imgsz, setImgsz] = useState(model.imgsz ?? 640);
  const [simplify, setSimplify] = useState(true);
  const sizeOk = Number.isInteger(imgsz) && imgsz >= 32 && imgsz <= 2048 && imgsz % 32 === 0;

  return (
    <form
      className="max-w-prose space-y-4"
      onSubmit={(e) => {
        e.preventDefault();
        add.mutate(
          { id: model.id, op, imgsz, simplify: op === "onnx_fp32" ? simplify : true },
          {
            onSuccess: () => {
              toast.success("The conversion was added to the grid");
            },
            onError: (err) => {
              toast.error(err.message);
            },
          },
        );
      }}
    >
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label="Format and precision">
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
          label="Input size (pixels)"
          help={`A multiple of 32 from 32 to 2048. This model was trained at ${String(model.imgsz ?? 640)}. Smaller is faster and usually less accurate.`}
        >
          {(id, describedBy) => (
            <Input
              id={id}
              aria-describedby={describedBy}
              type="number"
              inputMode="numeric"
              list="common-sizes"
              min={32}
              max={2048}
              step={32}
              value={imgsz}
              aria-invalid={!sizeOk}
              onChange={(e) => {
                setImgsz(Number(e.target.value));
              }}
            />
          )}
        </Field>
      </div>
      <datalist id="common-sizes">
        {SIZES.map((s) => (
          <option key={s} value={s} />
        ))}
      </datalist>
      {op === "onnx_fp32" ? (
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={simplify}
            onChange={(e) => {
              setSimplify(e.target.checked);
            }}
          />
          Simplify the ONNX graph (the default; turn it off to compare)
        </label>
      ) : null}
      <p className="text-sm text-muted-foreground">
        {op === "onnx_fp32" || op === "torchscript" || op.startsWith("ncnn")
          ? "Built from your original model."
          : "Built from the ONNX FP32 export at the same size, which is added too if it is missing."}
      </p>
      <Button type="submit" disabled={!sizeOk || add.isPending}>
        Add this conversion
      </Button>
    </form>
  );
}
