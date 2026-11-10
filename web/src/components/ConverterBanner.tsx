import { useConverter } from "@/lib/models";

/** Shown when the converter environment is not set up: models can be uploaded and kept, but not read or converted yet. */
export function ConverterBanner() {
  const converter = useConverter();
  if (!converter.data || converter.data.available) return null;
  return (
    <div role="alert" className="mb-6 max-w-prose border-l-2 border-warn pl-4 text-sm">
      <p className="font-medium">The converter is not set up on this computer.</p>
      <p className="mt-1 text-muted-foreground">{converter.data.message}</p>
      <p className="mt-1 text-muted-foreground">
        Models you upload are kept and checked, and are read and converted once it is set up. The
        steps are in converter/README.md.
      </p>
    </div>
  );
}
