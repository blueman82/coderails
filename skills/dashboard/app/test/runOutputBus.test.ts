import { describe, it, expect, vi } from "vitest";
import { createRunOutputBus } from "../src/lib/runOutputBus";

describe("createRunOutputBus", () => {
  it("delivers a published chunk to a subscribed listener", () => {
    const bus = createRunOutputBus();
    const listener = vi.fn();
    bus.subscribe(listener);
    bus.publish("run-1", "hello");
    expect(listener).toHaveBeenCalledWith({ runId: "run-1", chunk: "hello" });
  });

  it("delivers to multiple subscribers", () => {
    const bus = createRunOutputBus();
    const a = vi.fn();
    const b = vi.fn();
    bus.subscribe(a);
    bus.subscribe(b);
    bus.publish("run-1", "x");
    expect(a).toHaveBeenCalledTimes(1);
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("unsubscribe stops further delivery to that listener without affecting others", () => {
    const bus = createRunOutputBus();
    const a = vi.fn();
    const b = vi.fn();
    const unsubA = bus.subscribe(a);
    bus.subscribe(b);
    unsubA();
    bus.publish("run-1", "x");
    expect(a).not.toHaveBeenCalled();
    expect(b).toHaveBeenCalledTimes(1);
  });

  it("publish with no subscribers does not throw", () => {
    const bus = createRunOutputBus();
    expect(() => bus.publish("run-1", "x")).not.toThrow();
  });

  it("a listener that throws does not prevent other listeners from receiving the event, and does not propagate past publish()", () => {
    const bus = createRunOutputBus();
    const throwing = vi.fn(() => {
      throw new Error("boom");
    });
    const fine = vi.fn();
    bus.subscribe(throwing);
    bus.subscribe(fine);
    expect(() => bus.publish("run-1", "x")).not.toThrow();
    expect(fine).toHaveBeenCalledTimes(1);
  });
});
