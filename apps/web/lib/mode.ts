import type { BuilderIdState, PathfinderMode } from "./types.ts";

export function canEnterLive(state: BuilderIdState, loaded: boolean): boolean {
  return state === "live_aws" && loaded;
}

export function themeForMode(mode: PathfinderMode, liveGateOpen = false): "demo" | "live" {
  return mode === "live" || liveGateOpen ? "live" : "demo";
}

export function canExecuteDemoMutation(mode: PathfinderMode, demoEnabled: boolean): boolean {
  return mode === "demo" && demoEnabled;
}

export function showDemoControls(mode: PathfinderMode, liveGateOpen: boolean): boolean {
  return mode === "demo" && !liveGateOpen;
}

export function showLiveAuthControl(mode: PathfinderMode, liveGateOpen: boolean): boolean {
  return mode === "live" || liveGateOpen;
}
