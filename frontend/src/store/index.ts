import { create } from 'zustand';
import { CitySituationReport } from '@/types';

interface AppState {
  selectedZone: string | null;
  setSelectedZone: (zone: string | null) => void;
  report: CitySituationReport | null;
  setReport: (report: CitySituationReport) => void;
  isLive: boolean;
}

export const useAppStore = create<AppState>((set) => ({
  selectedZone: null,
  setSelectedZone: (zone) => set({ selectedZone: zone }),
  report: null,
  setReport: (report) => set({ report, isLive: true }),
  isLive: false,
}));
