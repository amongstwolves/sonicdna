import { Suspense } from "react";
import { AlchemyScreen } from "@/components/AlchemyScreen";

export default function AlchemyPage() {
  return (
    <Suspense>
      <AlchemyScreen />
    </Suspense>
  );
}
