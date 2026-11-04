import { Suspense } from "react";
import { DecodeScreen } from "@/components/DecodeScreen";

export default function DecodePage() {
  return (
    <Suspense>
      <DecodeScreen />
    </Suspense>
  );
}
