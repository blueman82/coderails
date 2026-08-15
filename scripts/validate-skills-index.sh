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

catalogs = {
  "skill" => "codex/skills/catalog.md",
  "agent" => "codex/agents/catalog.md",
  "command" => "codex/commands/catalog.md"
}
expected = {
  "skill" => Dir[File.join(root, "skills/*/SKILL.md")],
  "agent" => Dir[File.join(root, "agents/*.md")],
  "command" => Dir[File.join(root, "commands/*.md")]
}.transform_values { |paths| paths.map { |path| path.delete_prefix("#{root}/") }.sort }
seen = Hash.new { |hash, key| hash[key] = [] }

entries.each do |id, entry|
  abort "skills index: #{id.inspect} must be a non-empty mapping" unless id.is_a?(String) && entry.is_a?(Hash)
  %w[graph_role source_kind claude codex required_inputs output_contract].each do |key|
    abort "skills index: #{id} missing #{key}" unless entry.key?(key)
  end
  kind = entry["source_kind"]
  abort "skills index: #{id} has invalid source_kind" unless catalogs.key?(kind)
  seen[kind] << entry.dig("claude", "path")

  %w[claude codex].each do |provider|
    route = entry[provider]
    abort "skills index: #{id} #{provider} must be a mapping" unless route.is_a?(Hash)
    abort "skills index: #{id} #{provider} missing path/status" unless route.key?("path") && route.key?("status")
    abort "skills index: #{id} #{provider} has invalid status" unless %w[active planned].include?(route["status"])
    if route["status"] == "active"
      path = route["path"]
      resolved = path.is_a?(String) ? File.expand_path(path, root) : nil
      abort "skills index: active #{provider} implementation missing for #{id}" unless resolved && resolved.start_with?("#{root}/") && File.file?(resolved)
      abort "skills index: #{id} has wrong Codex catalog" if provider == "codex" && path != catalogs[kind]
    elsif !route["path"].nil?
      abort "skills index: planned #{provider} path must be null for #{id}"
    end
  end
  abort "skills index: #{id} has no active Claude implementation" unless entry.dig("claude", "status") == "active"
end

expected.each do |kind, paths|
  abort "skills index: #{kind} mapping is incomplete or has extras" unless seen[kind].sort == paths
end
puts "PASS skills/index.yaml (#{entries.length} entries)"
RUBY
