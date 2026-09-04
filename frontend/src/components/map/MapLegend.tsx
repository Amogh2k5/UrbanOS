export default function MapLegend() {
  return (
    <div className="absolute bottom-4 left-4 z-10 glass-panel-glow p-4 rounded-lg flex flex-col gap-3 text-sm">
      <div className="font-heading font-bold text-gray-300 mb-1 border-b border-gray-700 pb-2">INTELLIGENCE LEGEND</div>
      
      <div className="space-y-2">
        <div className="text-xs font-semibold text-gray-400 tracking-wider mb-1">ZONE RISK LEVEL</div>
        <div className="flex items-center gap-2 text-gray-200">
          <div className="w-4 h-4 rounded-full bg-blue-500 opacity-60"></div>
          <span>Low</span>
        </div>
        <div className="flex items-center gap-2 text-gray-200">
          <div className="w-4 h-4 rounded-full bg-yellow-500 opacity-60"></div>
          <span>Moderate</span>
        </div>
        <div className="flex items-center gap-2 text-gray-200">
          <div className="w-4 h-4 rounded-full bg-orange-500 opacity-60"></div>
          <span>High</span>
        </div>
        <div className="flex items-center gap-2 text-gray-200">
          <div className="w-4 h-4 rounded-full bg-red-600 opacity-60"></div>
          <span>Critical</span>
        </div>
      </div>

      <div className="space-y-2 mt-2 pt-2 border-t border-gray-700">
        <div className="text-xs font-semibold text-gray-400 tracking-wider mb-1">LIVE MARKERS</div>
        <div className="flex items-center gap-2 text-gray-200">
          <div className="w-3 h-3 bg-red-500 transform rotate-45 border border-red-200"></div>
          <span>Traffic Incident</span>
        </div>
        <div className="flex items-center gap-2 text-gray-200">
          <div className="w-3 h-3 rounded-full bg-cyan-400 border border-cyan-100 shadow-[0_0_8px_rgba(34,211,238,0.8)]"></div>
          <span>Flood Alert</span>
        </div>
      </div>
    </div>
  );
}
