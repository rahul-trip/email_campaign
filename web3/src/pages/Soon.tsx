import { Hammer } from "lucide-react";
import { Card, Empty } from "../ui/core";

/** A screen not rebuilt yet in web3. It says so plainly; web2 still has it at the same path. */
export function Soon({ screen }: { screen: string }) {
  return (
    <Card>
      <Empty art={<Hammer className="size-10 text-primary" />} title={`${screen} is being rebuilt`}>
        This screen is next in the web3 build. Until then, use it in the current app at the same address.
      </Empty>
    </Card>
  );
}
