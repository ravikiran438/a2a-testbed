// Registry of every browser-runnable conformance contract. Order
// mirrors `src/a2a_testbed/contracts/runner.py#transport_contracts`
// so the same agent passes/fails the same checks in the same order
// across the CLI and the browser surface.

import {
  agentCardCapabilitiesObject,
  agentCardHttpsUrls,
  agentCardPreferredInterface,
  agentCardProtocolVersionFormat,
  agentCardRequiredFields,
  agentCardSecuritySchemes,
  agentCardSkillAttributes,
  agentCardSkillIdUnique,
  agentCardSupportedInterfaces,
  agentCardUrlWellFormed,
  defaultModesDistinct,
  extensionsUriAbsolute,
  extensionsUriUnique,
  providerWellFormed,
  signaturesWellFormed,
  wellKnownCard,
} from './agent_card';
import {
  extendedCardCapabilityConsistency,
  pushNotificationsCapabilityConsistency,
  streamingCapabilityConsistency,
} from './capabilities';
import {
  iso8601Timestamps,
  jsonCamelCase,
} from './json_serialization';
import {
  errorDataAtype,
  jsonrpcEnvelope,
  jsonrpcErrorCodeRange,
  jsonrpcIdEcho,
  jsonrpcResultXorError,
  jsonrpcVersionField,
  methodNotFound,
  sendMessageRequiredFields,
} from './jsonrpc';
import {
  pushDeleteRemoves,
  pushFiresOnCompletion,
  pushGetReturnsConfig,
  pushGetTaskNotFound,
  pushListReturnsAll,
  pushSetPersists,
  pushSetTaskNotFound,
  streamingArtifactUpdateShape,
  streamingEventKinds,
  streamingFirstEventIsTask,
  streamingResponseContentType,
  streamingStatusUpdateShape,
  streamingTaskIdConsistency,
  streamingTerminalStateCloses,
  subscribeCapabilityRequired,
  subscribeNotFound,
  subscribeReplaysState,
  subscribeReturnsStream,
} from './streaming';
import {
  taskArtifactsShape,
  taskContextIdEchoed,
  taskHistoryShape,
  taskIdUuidFormat,
  taskStatusStateEnum,
  taskStatusTimestampPresent,
  tasksCancelNotFound,
  tasksCancelSetsCanceled,
  tasksGetNotFound,
  tasksGetReturnsTask,
  tasksListSortedDesc,
} from './tasks';
import type { Contract } from '../types';

export const ALL_CONTRACTS: Contract[] = [
  // AgentCard discovery + structural shape (§4.4, §8)
  wellKnownCard,
  agentCardRequiredFields,
  agentCardSkillAttributes,
  agentCardSkillIdUnique,
  agentCardCapabilitiesObject,
  agentCardSupportedInterfaces,
  agentCardPreferredInterface,
  agentCardUrlWellFormed,
  providerWellFormed,
  defaultModesDistinct,
  // Extension declarations (§4.4.4)
  extensionsUriAbsolute,
  extensionsUriUnique,
  // Signatures (§4.4 + §13)
  signaturesWellFormed,
  // Versioning (§3.6)
  agentCardProtocolVersionFormat,
  // Transport-level security (§7.1, §7.3)
  agentCardHttpsUrls,
  agentCardSecuritySchemes,
  // JSON serialization (§5.5, §5.6.1)
  jsonCamelCase,
  iso8601Timestamps,
  // JSON-RPC envelope + error semantics (§3.1.1, §9.3, §9.5)
  jsonrpcEnvelope,
  jsonrpcVersionField,
  jsonrpcIdEcho,
  jsonrpcResultXorError,
  jsonrpcErrorCodeRange,
  methodNotFound,
  sendMessageRequiredFields,
  // Error envelope (§3.3.2)
  errorDataAtype,
  // Capability ↔ method consistency (§3.1.2, §3.5, §3.1.7)
  streamingCapabilityConsistency,
  pushNotificationsCapabilityConsistency,
  extendedCardCapabilityConsistency,
  // Task lifecycle (§3.4, §4.1.1, §4.1.3)
  taskIdUuidFormat,
  taskStatusStateEnum,
  taskStatusTimestampPresent,
  taskHistoryShape,
  taskArtifactsShape,
  // GetTask / CancelTask / ListTasks (§3.1.3, §3.1.4, §3.1.5)
  tasksGetReturnsTask,
  tasksGetNotFound,
  tasksCancelSetsCanceled,
  tasksCancelNotFound,
  tasksListSortedDesc,
  // Multi-turn (§3.4.2)
  taskContextIdEchoed,
  // Streaming SSE (§3.1.2, §4.1.6, §4.1.7)
  streamingResponseContentType,
  streamingFirstEventIsTask,
  streamingEventKinds,
  streamingStatusUpdateShape,
  streamingArtifactUpdateShape,
  streamingTaskIdConsistency,
  streamingTerminalStateCloses,
  // Subscribe-to-task (§3.1.6)
  subscribeReturnsStream,
  subscribeReplaysState,
  subscribeNotFound,
  subscribeCapabilityRequired,
  // Push notifications (§3.1.7–§3.1.10, §3.5)
  pushSetPersists,
  pushGetReturnsConfig,
  pushListReturnsAll,
  pushDeleteRemoves,
  pushSetTaskNotFound,
  pushGetTaskNotFound,
  pushFiresOnCompletion,
];
