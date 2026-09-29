import type { FloodReading, FloodScenario } from "./types";
import { generateContinuousScenario } from "./generator";

export interface FloodDataSource {
  subscribe(handler: (reading: FloodReading) => void): () => void;
  start(): void;
  pause(): void;
  reset(): void;
  setScenario(scenario: FloodScenario): void;
  setSpeed(speed: number): void;
  readonly isRunning: boolean;
  readonly scenario: FloodScenario;
  readonly speed: number;
}

export class SimulationDataSource implements FloodDataSource {
  private handler: ((reading: FloodReading) => void) | null = null;
  private intervalId: ReturnType<typeof setInterval> | null = null;
  private tick = 0;
  private _isRunning = false;
  private _scenario: FloodScenario = "NORMAL";
  private _speed: number = 1;

  get isRunning(): boolean {
    return this._isRunning;
  }

  get scenario(): FloodScenario {
    return this._scenario;
  }

  get speed(): number {
    return this._speed;
  }

  subscribe(handler: (reading: FloodReading) => void): () => void {
    this.handler = handler;
    return () => {
      this.handler = null;
    };
  }

  start(): void {
    if (this._isRunning) return;
    this._isRunning = true;
    this.intervalId = setInterval(() => {
      this.tick++;
      const reading = generateContinuousScenario(this._scenario, this.tick);
      this.handler?.(reading);
    }, 2000 / this._speed);
  }

  pause(): void {
    this._isRunning = false;
    if (this.intervalId) {
      clearInterval(this.intervalId);
      this.intervalId = null;
    }
  }

  reset(): void {
    this.pause();
    this.tick = 0;
  }

  setScenario(scenario: FloodScenario): void {
    this._scenario = scenario;
    this.tick = 0;
    if (this._isRunning) {
      this.pause();
      this.start();
    }
  }

  setSpeed(speed: number): void {
    this._speed = speed;
    if (this._isRunning) {
      this.pause();
      this.start();
    }
  }
}
