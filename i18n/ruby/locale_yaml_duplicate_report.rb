# frozen_string_literal: true

# Lists locale YAML where the same top-level key (e.g. `auth`) appears in more than
# one file under `config/locales/<locale>/`: structural comparison, same-path value
# clashes, and sensible ordering (monolith key order when present).
#
#   ruby locale_yaml_duplicate_report.rb --rails-root /path/to/rails_app
#   ruby locale_yaml_duplicate_report.rb --rails-root /path/to/repo --app-subdir my_app
#   ruby locale_yaml_duplicate_report.rb --locale es
#
# If --rails-root is omitted, resolves from I18N_RAILS_ROOT / RAILS_ROOT or from
# `git rev-parse --show-toplevel` plus optional --app-subdir.

require "psych"
require "set"

def parse_args(argv)
  only = nil
  rails_root = nil
  app_subdir = ENV["I18N_RAILS_APP_SUBDIR"]
  i = 0
  while i < argv.length
    case argv[i]
    when "--locale", "-l"
      only = argv[i + 1] || abort("Missing value for --locale")
      i += 2
    when "--root", "--rails-root"
      rails_root = argv[i + 1] || abort("Missing value for #{argv[i]}")
      i += 2
    when "--app-subdir"
      app_subdir = argv[i + 1] || abort("Missing value for --app-subdir")
      i += 2
    when "-h", "--help"
      puts <<~HELP
        Usage: ruby locale_yaml_duplicate_report.rb [options]

        Options:
          --rails-root PATH   Rails app root (directory containing config/locales).
                              Also: --root PATH
          --app-subdir NAME   Monorepo: use ROOT/NAME/config/locales when ROOT/config/locales is missing
          --locale, -l CODE   Only report for one locale (e.g. es)
          -h, --help          This message

        Environment:
          I18N_RAILS_ROOT / RAILS_ROOT   Rails root when --rails-root is omitted
          I18N_RAILS_APP_SUBDIR          Default for --app-subdir
      HELP
      exit 0
    else
      abort "Unknown argument: #{argv[i]} (try --help)"
    end
  end
  [only, rails_root, app_subdir]
end

def try_rails_root_from_path(path, app_subdir)
  p = File.expand_path(path)
  return p if File.directory?(File.join(p, "config", "locales"))
  if app_subdir && !app_subdir.empty?
    nested = File.join(p, app_subdir)
    return nested if File.directory?(File.join(nested, "config", "locales"))
  end

  nil
end

def resolve_rails_root_from_path(path, app_subdir)
  r = try_rails_root_from_path(path, app_subdir)
  return r if r

  p = File.expand_path(path)
  tried = ["#{p}/config/locales"]
  tried << "#{File.join(p, app_subdir)}/config/locales" if app_subdir && !app_subdir.empty?
  abort <<~MSG.strip
    Could not find locale files. Tried:
      #{tried.join("\n      ")}
    Pass --rails-root to your Rails app root, or a monorepo root with --app-subdir.
  MSG
end

def discover_rails_root_from_cwd_git(app_subdir)
  top = IO.popen(["git", "rev-parse", "--show-toplevel"], err: File::NULL, &:read).to_s.strip
  return nil if top.empty?

  try_rails_root_from_path(top, app_subdir)
end

def resolve_rails_root(cli_path, app_subdir)
  explicit = cli_path || ENV["I18N_RAILS_ROOT"] || ENV["RAILS_ROOT"]
  return resolve_rails_root_from_path(explicit, app_subdir) if explicit

  from_git = discover_rails_root_from_cwd_git(app_subdir)
  return from_git if from_git

  abort <<~MSG.strip
    Could not determine Rails root. Pass --rails-root, set I18N_RAILS_ROOT / RAILS_ROOT,
    or run from a Git repo whose root contains config/locales (optionally with --app-subdir).
  MSG
end

def load_yaml(path)
  raw = File.read(path)
  Psych.safe_load(raw, permitted_classes: [Symbol], aliases: true)
end

def locale_yaml_files(locale_dir, locale)
  Dir.glob(File.join(locale_dir, "*.yml")).sort.select do |path|
    base = File.basename(path)
    base == "#{locale}.yml" || base.end_with?(".#{locale}.yml")
  end
end

def tree_for_locale(data, locale)
  return {} unless data.is_a?(Hash)

  data[locale] || data[locale.to_sym]
end

# Dot paths to leaf values (non-Hash or empty Hash).
def leaf_paths(obj, prefix = "")
  out = {}
  case obj
  when Hash
    if obj.empty?
      out[prefix] = {}
      return out
    end
    obj.each do |k, v|
      p = prefix.empty? ? k.to_s : "#{prefix}.#{k}"
      if v.is_a?(Hash) && !v.empty?
        out.merge!(leaf_paths(v, p))
      else
        out[p] = v
      end
    end
  else
    out[prefix] = obj
  end
  out
end

# Set of dot paths from this subtree's root to each leaf (keys only; ignores values).
def leaf_key_skeleton(tree)
  return Set.new if tree.nil?
  return Set.new([""]) unless tree.is_a?(Hash)

  Set.new(leaf_paths(tree).keys)
end

# Depth-first leaf dot paths under `tree`, same strings as `leaf_paths` keys, in YAML key order.
def ordered_leaf_paths(obj, prefix = "")
  case obj
  when Hash
    if obj.empty?
      return [prefix]
    end

    obj.flat_map do |k, v|
      p = prefix.empty? ? k.to_s : "#{prefix}.#{k}"
      if v.is_a?(Hash) && !v.empty?
        ordered_leaf_paths(v, p)
      else
        [p]
      end
    end
  else
    prefix.empty? ? [] : [prefix]
  end
end

# Stable ordering: paths appear in the order they first occur across `trees` (nil skipped).
def sort_path_set_by_yaml_trees(path_set, *trees)
  rank = {}
  n = 0
  trees.compact.each do |tree|
    ordered_leaf_paths(tree).each do |p|
      rank[p] ||= (n += 1)
    end
  end
  tail = n + 1
  path_set.to_a.sort_by { |p| [rank.fetch(p, tail), p] }
end

def subtree_for_branch(tree, branch_key)
  return nil unless tree.is_a?(Hash)

  tree[branch_key] || tree[branch_key.to_sym]
end

def top_level_key_order_from_base(locale, per_file_tree)
  base_name = "#{locale}.yml"
  tree = per_file_tree[base_name]
  return [] unless tree.is_a?(Hash)

  tree.keys.map(&:to_s)
end

# Keys not present in `base_key_order` (e.g. duplicate only in breakouts, not in monolith)
# all share the same sort rank `tail`, then tie-break by `k` — no crash, stable order.
def dup_top_keys_in_base_order(dup_top, base_key_order)
  return dup_top.sort if base_key_order.empty?

  index = base_key_order.each_with_index.to_h
  tail = base_key_order.length
  dup_top.sort_by { |k| [index.fetch(k, tail), k] }
end

MAX_STRUCTURE_PATHS = 48

def print_indented_paths(label, path_set, indent: "        ", base_subtree: nil, focal_subtree: nil)
  puts "#{indent}#{label}"
  if path_set.empty?
    puts "#{indent}  (no unique key branch paths)"
    return
  end

  sorted =
    if base_subtree || focal_subtree
      sort_path_set_by_yaml_trees(path_set, base_subtree, focal_subtree)
    else
      path_set.to_a.sort
    end
  sorted.first(MAX_STRUCTURE_PATHS).each do |p|
    disp = p.empty? ? "(empty branch)" : p
    puts "#{indent}  - #{disp}"
  end
  return unless sorted.size > MAX_STRUCTURE_PATHS

  puts "#{indent}  … #{sorted.size - MAX_STRUCTURE_PATHS} more paths"
end

def report_branch_structure(locale, branch_key, filenames, per_file_tree)
  base_tree = per_file_tree["#{locale}.yml"]
  base_branch = subtree_for_branch(base_tree, branch_key)

  subtrees = {}
  filenames.each do |name|
    t = per_file_tree[name]
    next unless t.is_a?(Hash)

    sub = subtree_for_branch(t, branch_key)
    subtrees[name] = sub
  end

  skeletons = subtrees.transform_values { |sub| leaf_key_skeleton(sub) }
  names = filenames.sort
  sets = names.map { |n| skeletons[n] }
  ref = sets.first
  all_match = names.all? { |n| skeletons[n] == ref }

  if all_match
    puts "  #{branch_key} -  Same structure (#{ref.size} leaf paths) in all files."
    names.each { |n| puts "    - #{locale}/#{n}" }
    return
  end

  puts "  #{branch_key}"

  if names.size == 2
    n0, n1 = names[0], names[1]
    only0 = skeletons[n0] - skeletons[n1]
    only1 = skeletons[n1] - skeletons[n0]
    sub0 = subtrees[n0]
    sub1 = subtrees[n1]
    puts "      #{locale}/#{n0}"
    print_indented_paths("Leaf keys only in this file:", only0, indent: "        ",
      base_subtree: base_branch, focal_subtree: sub0)
    puts "      #{locale}/#{n1}"
    print_indented_paths("Leaf keys only in this file:", only1, indent: "        ",
      base_subtree: base_branch, focal_subtree: sub1)
    return
  end

  names.each { |n| puts "    - #{locale}/#{n}" }

  names.each do |n|
    others = names - [n]
    next if others.empty?

    sk_others = others.map { |m| skeletons[m] }
    inter_others = sk_others.inject(:&)
    only_here = skeletons[n] - inter_others
    missing_here = inter_others - skeletons[n]
    next if only_here.empty? && missing_here.empty?

    focal = subtrees[n]
    puts "      #{locale}/#{n}"
    print_indented_paths("Leaf keys in this file but not in every other file:", only_here, indent: "        ",
      base_subtree: base_branch, focal_subtree: focal)
    print_indented_paths("Leaf keys in every other file but not in this file:", missing_here, indent: "        ",
      base_subtree: base_branch, focal_subtree: focal)
  end
end

def stable_repr(v)
  case v
  when Hash, Array
    Psych.dump(v).strip
  else
    v.inspect
  end
end

only_locale, cli_rails_root, app_subdir = parse_args(ARGV)
rails_root = resolve_rails_root(cli_rails_root, app_subdir)
LOCALES_ROOT = File.join(rails_root, "config", "locales")

unless File.directory?(LOCALES_ROOT)
  abort "Missing locales directory: #{LOCALES_ROOT}"
end

locale_dirs = Dir.children(LOCALES_ROOT).select { |e| File.directory?(File.join(LOCALES_ROOT, e)) }.sort
locale_dirs = locale_dirs.select { |e| e == only_locale } if only_locale

found_any = false

locale_dirs.each do |locale|
  dir = File.join(LOCALES_ROOT, locale)
  files = locale_yaml_files(dir, locale)
  next if files.empty?

  per_file_top = {}
  per_file_leaves = {}
  per_file_tree = {}

  files.each do |path|
    rel = File.join(locale, File.basename(path))
    data = load_yaml(path)
    tree = tree_for_locale(data, locale)
    unless tree.is_a?(Hash)
      warn "Skip #{rel}: no `#{locale}:` root hash"
      next
    end

    name = File.basename(path)
    per_file_top[name] = tree.keys.map(&:to_s).to_set
    per_file_leaves[name] = leaf_paths(tree)
    per_file_tree[name] = tree
  end

  next if per_file_top.empty?

  all_top = per_file_top.values.reduce(Set.new) { |a, s| a.merge(s) }

  dup_top = all_top.select do |key|
    per_file_top.count { |_, keys| keys.include?(key) } > 1
  end

  # Leaf path -> { basename => value }
  leaf_to_files = Hash.new { |h, k| h[k] = {} }
  per_file_leaves.each do |fname, leaves|
    leaves.each do |path, val|
      leaf_to_files[path][fname] = val
    end
  end

  value_conflicts = leaf_to_files.select do |_path, fv|
    fv.size > 1 && fv.values.map { |v| stable_repr(v) }.uniq.size > 1
  end

  next if dup_top.empty? && value_conflicts.empty?
  found_any = true

  puts "=" * 72
  puts "Locale: #{locale}"
  puts "=" * 72

  base_key_order = top_level_key_order_from_base(locale, per_file_tree)
  base_full_tree = per_file_tree["#{locale}.yml"]

  unless dup_top.empty?
    puts "\n## Duplicate top-level branches (same key under `#{locale}:` in multiple files)"
    dup_top_keys_in_base_order(dup_top, base_key_order).each do |key|
      names = per_file_top.select { |_, keys| keys.include?(key) }.keys.sort
      report_branch_structure(locale, key, names, per_file_tree)
    end
  end

  unless value_conflicts.empty?
    puts "\n## Same leaf path, different values (merge would pick one source)"
    conflict_paths_ordered =
      if base_full_tree.is_a?(Hash)
        sort_path_set_by_yaml_trees(Set.new(value_conflicts.keys), base_full_tree)
      else
        value_conflicts.keys.sort
      end
    conflict_paths_ordered.each do |path|
      puts "  #{path}"
      leaf_to_files[path].sort.each do |fname, val|
        puts "    #{locale}/#{fname}: #{stable_repr(val)}"
      end
    end
  end

  puts ""
end

puts "Scanned: #{LOCALES_ROOT}"
puts "Rails root: #{rails_root}"
puts "No shared translation key YAML branches found." unless found_any
puts "Done."
