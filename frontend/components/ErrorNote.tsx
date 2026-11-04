import { ApiError } from "@/lib/api";

export function ErrorNote({ error }: { error: unknown }) {
  const message = error instanceof Error ? error.message : String(error);
  const fix = error instanceof ApiError ? error.fix : null;
  return (
    <div className="error-note" role="alert">
      <strong>{message}</strong>
      {fix ? <span>{fix}</span> : null}
    </div>
  );
}
