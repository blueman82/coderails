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
abort "skills index: version must be 1" unless data["version"] == 1
skills = data["skills"]
abort "skills index: skills must be a non-empty list" unless skills.is_a?(Array) && !skills.empty?

ids = {}
claude_paths = []
skills.each_with_index do |skill, i|
  abort "skills index: entry #{i} must be a mapping" unless skill.is_a?(Hash)
  %w[id graph_role claude_path codex_path required_inputs output_contract status provider_status routing_triggers].each do |key|
    abort "skills index: entry #{i} missing #{key}" unless skill.key?(key)
  end
  id = skill["id"]
  abort "skills index: duplicate or invalid id #{id.inspect}" unless id.is_a?(String) && id.match?(/\Acoderails\.[a-z0-9-]+\z/) && ids[id].nil?
  ids[id] = true
  claude_paths << skill["claude_path"]
  abort "skills index: #{id} has invalid status" unless %w[active planned].include?(skill["status"])
  providers = skill["provider_status"]
  abort "skills index: #{id} provider_status must name claude and codex" unless providers.is_a?(Hash) && %w[claude codex].all? { |p| %w[active planned].include?(providers[p]) }
  %w[claude codex].each do |provider|
    path = skill["#{provider}_path"]
    if providers[provider] == "active"
      abort "skills index: active #{provider} implementation missing for #{id}" unless path.is_a?(String) && File.file?(File.join(root, path))
    elsif !path.nil? && File.file?(File.join(root, path))
      abort "skills index: planned #{provider} implementation is routable for #{id}"
    end
  end
  abort "skills index: #{id} requires non-empty routing_triggers" unless skill["routing_triggers"].is_a?(Array) && skill["routing_triggers"].any? { |t| t.is_a?(String) && !t.empty? }
end
expected = Dir[File.join(root, "skills/*/SKILL.md")].map { |path| path.delete_prefix("#{root}/") }.sort
abort "skills index: active skill mapping is incomplete" unless expected == claude_paths.sort
puts "PASS skills/index.yaml (#{skills.length} skills)"
RUBY
