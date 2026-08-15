#!/bin/bash
set -euo pipefail

root=$(cd "$(dirname "$0")/.." && pwd)
index=${1:-"$root/skills/index.yaml"}

INDEX="$index" ROOT="$root" ruby <<'RUBY'
require "yaml"

index = ENV.fetch("INDEX")
root = ENV.fetch("ROOT")
data = YAML.safe_load(File.read(index), permitted_classes: [], aliases: false)
abort "skills index: root must be a mapping" unless data.is_a?(Hash)
abort "skills index: root must contain only skills" unless data.keys == ["skills"]

entries = data["skills"]
abort "skills index: skills must be a non-empty mapping" unless entries.is_a?(Hash) && !entries.empty?

directories = {
  "skill" => {"claude" => "skills", "codex" => "codex/skills"},
  "agent" => {"claude" => "agents", "codex" => "codex/agents"},
  "command" => {"claude" => "commands", "codex" => "codex/commands"}
}
expected = {
  "claude" => {
    "skill" => Dir[File.join(root, "skills/*/SKILL.md")],
    "agent" => Dir[File.join(root, "agents/*.md")],
    "command" => Dir[File.join(root, "commands/*.md")]
  },
  "codex" => {
    "skill" => Dir[File.join(root, "codex/skills/*.md")],
    "agent" => Dir[File.join(root, "codex/agents/*.md")],
    "command" => Dir[File.join(root, "codex/commands/*.md")]
  }
}.transform_values { |kinds| kinds.transform_values { |paths| paths.map { |path| path.delete_prefix("#{root}/") }.sort } }
seen = Hash.new { |providers, provider| providers[provider] = Hash.new { |kinds, kind| kinds[kind] = [] } }

entries.each do |id, entry|
  abort "skills index: #{id.inspect} must be a non-empty mapping" unless id.is_a?(String) && entry.is_a?(Hash)
  %w[graph_role source_kind claude codex required_inputs output_contract].each do |key|
    abort "skills index: #{id} missing #{key}" unless entry.key?(key)
  end
  kind = entry["source_kind"]
  abort "skills index: #{id} has invalid source_kind" unless directories.key?(kind)

  %w[claude codex].each do |provider|
    route = entry[provider]
    abort "skills index: #{id} #{provider} must be a mapping" unless route.is_a?(Hash)
    abort "skills index: #{id} #{provider} missing path/status" unless route.key?("path") && route.key?("status")
    abort "skills index: #{id} #{provider} has invalid status" unless %w[active planned].include?(route["status"])
    if route["status"] == "active"
      path = route["path"]
      resolved = path.is_a?(String) ? File.expand_path(path, root) : nil
      abort "skills index: active #{provider} implementation missing for #{id}" unless resolved && resolved.start_with?("#{root}/") && File.file?(resolved)
      expected_prefix = "#{directories[kind][provider]}/"
      abort "skills index: #{id} has wrong #{provider} kind directory" unless path.start_with?(expected_prefix)
      seen[provider][kind] << path
    elsif !route["path"].nil?
      abort "skills index: planned #{provider} path must be null for #{id}"
    end
  end
  abort "skills index: #{id} has no active Claude implementation" unless entry.dig("claude", "status") == "active"
end

expected.each do |provider, kinds|
  kinds.each do |kind, paths|
    abort "skills index: #{provider} #{kind} mapping is incomplete or has extras" unless seen[provider][kind].sort == paths
  end
end
puts "PASS skills/index.yaml (#{entries.length} entries)"
RUBY
