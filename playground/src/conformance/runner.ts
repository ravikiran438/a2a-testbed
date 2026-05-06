// Browser-side conformance runner. Calls every contract sequentially
// (contracts are short and bounded; concurrency wouldn't help and
// would surprise rate limiters that bucket per-IP). Mirrors the
// Python runner's behavior — strict pass / soft pass / fail — so
// the same scenario produces the same verdict regardless of
// surface.

import { ALL_CONTRACTS } from './contracts';
import type { Contract, ContractResult } from './types';

export async function runConformanceSweep(
  agentUrl: string,
): Promise<ContractResult[]> {
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
