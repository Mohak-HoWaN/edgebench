import { useQueryClient } from "@tanstack/react-query";
import { Upload } from "lucide-react";
import { useRef, useState, type DragEvent } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { modelsKey, uploadModel } from "@/lib/models";
import { cn } from "@/lib/utils";

/** Drop a .pt file, or choose one. The server checks it before keeping it, and its reason for refusing is shown as written. */
export function UploadZone() {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState<number | null>(null);
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const uploading = progress !== null;

  async function send(file: File) {
    setError(null);
    setName(file.name);
    setProgress(0);
    try {
      const { model, existing } = await uploadModel(file, setProgress);
      await queryClient.invalidateQueries({ queryKey: modelsKey });
      if (existing) toast.info("That exact file was uploaded before. Here is its model.");
      void navigate(`/models/${String(model.id)}`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "The upload failed.");
    } finally {
      setProgress(null);
      if (input.current) input.current.value = ""; // choosing the same file again must fire a change
    }
  }

  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setDragging(false);
    const file = e.dataTransfer.files[0];
    if (file && !uploading) void send(file);
  };

  return (
    <div className="max-w-prose">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => {
          setDragging(false);
        }}
        onDrop={onDrop}
        className={cn(
          "flex flex-col items-start gap-3 rounded-lg border border-dashed p-6 transition-colors",
          dragging ? "border-primary bg-accent" : "border-input",
        )}
      >
        <p className="text-sm">
          Drop a PyTorch model here. It is checked first, then converted to every format you can
          benchmark.
        </p>
        <input
          ref={input}
          type="file"
          accept=".pt"
          className="sr-only"
          aria-label="Choose a PyTorch model file (.pt)"
          tabIndex={-1}
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) void send(file);
          }}
        />
        <Button
          variant="outline"
          disabled={uploading}
          onClick={() => {
            input.current?.click();
          }}
        >
          <Upload aria-hidden />
          Choose a .pt file
        </Button>
        {uploading ? (
          <div className="w-full">
            <progress
              className="h-2 w-full"
              value={progress}
              max={1}
              aria-label={`Uploading ${name}`}
            />
            <p className="mt-1 text-xs text-muted-foreground" role="status">
              {progress >= 1
                ? `Checking ${name}`
                : `Uploading ${name}, ${String(Math.round(progress * 100))}%`}
            </p>
          </div>
        ) : null}
      </div>
      {error ? (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {error}
        </p>
      ) : null}
    </div>
  );
}
