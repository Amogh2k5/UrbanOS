import TransitMap from "@/components/map/TransitMap";

export default function TransitPage() {
  return (
    <div className="container mx-auto px-4 py-6">
      <div className="mb-6">
        <h1 className="text-3xl font-heading font-bold text-white">Transit Network</h1>
        <p className="text-gray-400 mt-1">Singapore bus routes, stops, and train service alerts</p>
      </div>
      <TransitMap />
    </div>
  );
}