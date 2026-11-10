import { EmptyState } from "@/components/EmptyState";
import { PageHeader } from "@/components/PageHeader";

export default function NotFound() {
  return (
    <>
      <PageHeader title="Page not found" />
      <EmptyState
        title="There is nothing at this address"
        action={{ label: "Go to the dashboard", to: "/" }}
      >
        The link may be old, or the page may not exist in this version of EdgeBench.
      </EmptyState>
    </>
  );
}
