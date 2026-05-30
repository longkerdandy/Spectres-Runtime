import type { Plugin } from "@opencode-ai/plugin"

/**
 * git-attribution
 *
 * Marks every commit opencode makes (via its bash tool) with two trailers:
 *
 *   Co-authored-by: opencode <noreply@opencode.ai>
 *   Opencode-Model: <providerID>/<model id>
 *
 * The email is deliberately NOT in GitHub's `@users.noreply.github.com`
 * namespace: GitHub resolves that namespace to real usernames, so
 * `opencode@users.noreply.github.com` would mis-link to the unrelated account
 * github.com/OpenCode. A plain-domain noreply (same pattern as Claude Code's
 * `noreply@anthropic.com`) renders as a plain-text co-author with no false
 * profile link.
 *
 * The model is captured dynamically from the `chat.params` hook (fired before
 * every LLM request, where `model` is always present), so the trailer always
 * reflects whatever model the session is actually running — nothing is
 * hard-coded.
 *
 * Only commits issued through opencode's bash tool are touched; commits you
 * make by hand in a terminal are left untouched, keeping attribution honest.
 */
export const GitAttribution: Plugin = async () => {
  // Updated on every request; holds the currently active model, e.g.
  // "github-copilot/claude-opus-4.8".
  let model: string | undefined

  return {
    "chat.params": async (input) => {
      try {
        const id = input?.model?.id
        const provider = input?.model?.providerID
        if (id) model = provider ? `${provider}/${id}` : id
      } catch {
        // Never let attribution bookkeeping break a request.
      }
    },

    "tool.execute.before": async (input, output) => {
      try {
        if (input?.tool !== "bash") return

        const command: unknown = output?.args?.command
        if (typeof command !== "string") return

        // Only touch invocations that actually create a commit.
        if (!/\bgit\s+commit\b/.test(command)) return

        // Idempotent: skip if we (or anything) already added trailers.
        if (/Opencode-Model:/i.test(command) || /Co-authored-by:\s*opencode/i.test(command)) {
          return
        }

        const trailers = [
          `--trailer "Co-authored-by: opencode <noreply@opencode.ai>"`,
          model ? `--trailer "Opencode-Model: ${model}"` : "",
        ]
          .filter(Boolean)
          .join(" ")

        // Insert right after the `git commit` token so the trailers bind to
        // the commit even in chains like `git add . && git commit -m "..."`.
        output.args.command = command.replace(/\bgit\s+commit\b/, (m) => `${m} ${trailers}`)
      } catch {
        // On any failure, leave the command untouched — a missing trailer is
        // strictly better than a blocked commit.
      }
    },
  }
}
