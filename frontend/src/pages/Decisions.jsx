import { useEffect } from "react";
import DecisionCard from "../components/DecisionCard";
import { useLive } from "../context/LiveContext";
import { Empty, PageTitle } from "../components/ui";

// The Decision inbox: every run that is paused and waiting for a human. It survives a page refresh or a server restart.
export default function Decisions() {
  const { pending, refreshPending } = useLive();
  useEffect(() => { refreshPending(); }, [refreshPending]);
  return (
    <div className="max-w-3xl">
      <PageTitle title="Decisions" sub="When M.I.N.D is not sure how a new statement fits with an older memory, it pauses and asks. Your answer resumes exactly where it stopped." />
      {pending.length === 0 ? <Empty>Nothing is waiting for you.</Empty> : (
        <div className="space-y-3">{pending.map((d) => <DecisionCard key={d.id} d={d} />)}</div>
      )}
    </div>
  );
}
