// Browser-side conformance runner. Calls every contract sequentially
// (contracts are short and bounded; concurrency wouldn't help and
// would surprise rate limiters that bucket per-IP). Mirrors the
// Python runner's behavior — strict pass / soft pass / fail — so
// the same scenario produces the same verdict regardless of
// surface.

import { clearAllSweepCaches } from './cache';
import { ALL_CONTRACTS } from './contracts';
import type { Contract, ContractResult } from './types';

/** Default chunk size for `runConformanceChunk`. Sized to leave
 *  headroom inside a typical per-IP rate-limit window so the user
 *  can re-run a chunk without tripping limits. */
export const CHUNK_SIZE = 10;

/**
 * Run a slice of the contract list. Used by the playground UI to
 * pace requests against rate-limited external agents — the user
 * clicks through batches instead of bursting all 58 calls at once.
 *
 * `startIndex === 0` clears every per-sweep cache so a fresh
 * sweep sees current agent state. Subsequent chunks reuse the
 * cache (AgentCard, etc.) since they're part of the same sweep.
 */
export async function runConformanceChunk(
  agentUrl: string,
  startIndex: number,
  size: number = CHUNK_SIZE,
): Promise<ContractResult[]> {
  if (startIndex === 0) clearAllSweepCaches();
  const end = Math.min(startIndex + size, ALL_CONTRACTS.length);
  const out: ContractResult[] = [];
  for (let i = startIndex; i < end; i++) {
    out.push(await runOne(ALL_CONTRACTS[i], agentUrl));
  }
  return out;
}

export async function runConformanceSweep(
  agentUrl: string,
): Promise<ContractResult[]> {
  // Drop every per-sweep cache (AgentCard today, plus anything else
  // helpers register later) so a fresh sweep sees current agent state.
  clearAllSweepCaches();
  const results: ContractResult[] = [];
  for (const contract of ALL_CONTRACTS) {
    results.push(await runOne(contract, agentUrl));
  }
  return results;
}

async function runOne(
  contract: Contract,
  agentUrl: string,
): Promise<ContractResult> {
  try {
    const detail = await contract.verify(agentUrl);
    const detailStr = typeof detail === 'string' ? detail : '';
    return {
      contractId: contract.id,
      specSection: contract.specSection,
      category: contract.category,
      passed: true,
      softPass: detailStr.length > 0,
      detail: detailStr,
    };
  } catch (err) {
    return {
      contractId: contract.id,
      specSection: contract.specSection,
      category: contract.category,
      passed: false,
      softPass: false,
      detail: (err as Error).message ?? String(err),
    };
  }
}

export interface ConformanceSummary {
  total: number;
  passed: number;
  failed: number;
  softPasses: number;
}

export function summarize(results: ContractResult[]): ConformanceSummary {
  let passed = 0;
  let failed = 0;
  let softPasses = 0;
  for (const r of results) {
    if (r.passed) passed += 1;
    else failed += 1;
    if (r.softPass) softPasses += 1;
  }
  return { total: results.length, passed, failed, softPasses };
}
