import TransitMap from "@/components/map/TransitMap";
import { domainAccentClass } from "@/components/city/presentation";

export default function TransitPage() {
  return (
    <div className="container mx-auto px-4 py-6">
      <div className="mb-6 flex items-center gap-3">
        <span className={`w-2 h-9 rounded-full ${domainAccentClass("transit")}`} aria-hidden="true" />
        <div>
          <h1 className="text-3xl font-heading font-bold text-slate-900">Transit Network</h1>
          <p className="text-slate-500 mt-1">Singapore bus routes, stops, and train service alerts</p>
        </div>
      </div>
      <TransitMap />
    </div>
  );
}