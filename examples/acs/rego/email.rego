# Rego policy for the email-agent ACS manifest (examples/acs/email-agent-rego.acs.yaml).
#
# Evaluated by OPA via a2a_testbed.acs.rego.RegoBackend. The ACS canonical
# policy input is the OPA `input` document, so this reads the projected
# tool arguments at `input.policy_target.value`. The manifest binds
# `query: data.email_agent.verdict`.
#
# Returns an ACS decision string: "deny" for external recipients, else
# the default "allow".

package email_agent

import rego.v1

default verdict := "allow"

verdict := "deny" if {
	to := input.policy_target.value.message.to
	endswith(to, "@external.example")
}
