import { Suspense } from "react";
import { LabScreen } from "@/components/LabScreen";

export default function LabPage() {
  return (
    <Suspense>
      <LabScreen />
    </Suspense>
  );
}
