// Browser-side equivalent of `a2a_testbed.contracts.base`. Every
// contract is a small async function that throws on failure, returns
// nothing on strict pass, or returns a string detail to record a
// soft pass (e.g. "capability honored but with the wrong error code").
// The runner catches the three cases and produces a uniform result.

export type ContractCategory = 'transport' | 'network';

export interface Contract {
  /** Stable identifier across releases (matches the Python contract id). */
  id: string;
  /** A2A spec section the contract derives from, or null for testbed-original. */
  specSection: string | null;
  /** One-line human-readable summary. */
  description: string;
  category: ContractCategory;
  /**
   * Verify the contract against the given agent URL.
   * - `throw` to fail (any Error / AssertionError equivalent).
   * - `return undefined` for a strict pass with no detail.
   * - `return string` for a soft pass with the deviation in the
   *   detail column (mirrors the Python runner's behavior).
   */
  verify: (agentUrl: string) => Promise<undefined | string>;
}

export interface ContractResult {
  contractId: string;
  specSection: string | null;
  category: ContractCategory;
  /** True for both strict and soft passes; false only when verify threw. */
  passed: boolean;
  /** True when verify returned a non-empty deviation string. */
  softPass: boolean;
  detail: string;
}
