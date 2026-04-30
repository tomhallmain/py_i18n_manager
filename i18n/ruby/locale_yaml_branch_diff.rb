# frozen_string_literal: true

# Compare merged locale YAML between two git refs (default: main vs current HEAD).
# Checks out each ref in turn, loads every *.yml under config/locales (Rails root),
# deep-merges by top-level locale key (e.g. es, en), then prints (1) key path diffs,
# (2) value diffs.
#
# Run from anywhere if you pass the Rails app root (directory that contains
# config/locales), or set I18N_RAILS_ROOT / RAILS_ROOT. Git is always invoked with -C
# so the script does not depend on your cwd being inside the repo.
#
# Usage:
#   ruby locale_yaml_branch_diff.rb --rails-root /path/to/rails_app
#   ruby locale_yaml_branch_diff.rb --rails-root /path/to/monorepo --app-subdir my_rails_app
#   I18N_RAILS_ROOT=/path/to/rails_app ruby locale_yaml_branch_diff.rb --base develop --compare feature/x
#
# From inside the repo you can omit --rails-root; discovery uses git rev-parse
# from the current working directory.
#
# Requires a clean git working tree so checkouts are safe.

require "psych"
require "set"

DEFAULT_BASE = "main"

def parse_args(argv)
  base = ENV["I18N_YAML_DIFF_BASE"] || DEFAULT_BASE
  compare = nil
  rails_root = nil
  app_subdir = ENV["I18N_RAILS_APP_SUBDIR"]
  i = 0
  while i < argv.length
    case argv[i]
    when "--base"
      base = argv[i + 1] || abort("Missing value for --base")
      i += 2
    when "--compare"
      compare = argv[i + 1] || abort("Missing value for --compare")
      i += 2
    when "--root", "--rails-root"
      rails_root = argv[i + 1] || abort("Missing value for #{argv[i]}")
      i += 2
    when "--app-subdir"
      app_subdir = argv[i + 1] || abort("Missing value for --app-subdir")
      i += 2
    when "-h", "--help"
      puts <<~HELP
        Usage: ruby locale_yaml_branch_diff.rb [options]

        Options:
          --rails-root PATH   Rails app root (directory containing config/locales).
                              Also accepted: --root PATH
          --app-subdir NAME   If PATH is a monorepo root, use PATH/NAME/config/locales
                              when PATH/config/locales is missing (optional).
          --base REF            First ref to checkout and snapshot (default: #{DEFAULT_BASE}, or I18N_YAML_DIFF_BASE)
          --compare REF         Second ref (default: current HEAD at script start)
          -h, --help             This message

        Environment:
          I18N_RAILS_ROOT      Rails root if --rails-root is omitted
          RAILS_ROOT           Same, if I18N_RAILS_ROOT is unset
          I18N_RAILS_APP_SUBDIR  Default for --app-subdir when flag is omitted
          I18N_YAML_DIFF_BASE  Default for --base when flag is omitted

        If no Rails root is given, the script runs `git rev-parse --show-toplevel`
        from the process cwd and looks for ./config/locales or ./NAME/config/locales
        when NAME is set via --app-subdir or I18N_RAILS_APP_SUBDIR.

        Requires a clean git working tree. Restores your previous branch when done.
      HELP
      exit 0
    else
      abort "Unknown argument: #{argv[i]} (try --help)"
    end
  end
  [base, compare, rails_root, app_subdir]
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
    Pass --rails-root to your Rails app root (the directory that contains config/locales),
    or --rails-root to a monorepo root plus --app-subdir for the Rails app folder name.
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
    Could not determine Rails root. Either:
      --rails-root /path/to/rails_app
    or set I18N_RAILS_ROOT / RAILS_ROOT, or run from inside the Git repo so
    `git rev-parse --show-toplevel` finds a tree with config/locales (optionally with --app-subdir).
  MSG
end

def git_root_for_rails_app(rails_root)
  out = IO.popen(["git", "-C", rails_root, "rev-parse", "--show-toplevel"], err: File::NULL, &:read)
  root = out.to_s.strip
  abort("Not a git repository (git rev-parse failed for -C #{rails_root}).") if root.empty?

  root
end

def git_capture(git_root, *args)
  IO.popen(["git", "-C", git_root, *args], err: [:child, :out], &:read).strip
end

def git_system(git_root, *args)
  system("git", "-C", git_root, *args, out: File::NULL, err: File::NULL)
end

def ref_exists?(git_root, ref)
  git_system(git_root, "rev-parse", "-q", "--verify", ref)
end

def ensure_clean_tree!(git_root)
  dirty = git_capture(git_root, "status", "--porcelain")
  return if dirty.empty?

  warn "Working tree is not clean; refusing to checkout branches."
  warn dirty
  exit 1
end

def checkout!(git_root, ref)
  ok = system("git", "-C", git_root, "checkout", "-q", ref)
  abort("git checkout #{ref} failed") unless ok
end

def current_branch(git_root)
  b = git_capture(git_root, "branch", "--show-current")
  b.empty? ? nil : b
end

def deep_merge(a, b)
  return deep_copy(b) unless a.is_a?(Hash) && b.is_a?(Hash)

  a.merge(b) do |_, old_val, new_val|
    if old_val.is_a?(Hash) && new_val.is_a?(Hash)
      deep_merge(old_val, new_val)
    else
      new_val
    end
  end
end

def deep_copy(obj)
  Marshal.load(Marshal.dump(obj))
end

def load_all_locale_yamls(locales_glob)
  merged_by_locale = Hash.new { |h, k| h[k] = {} }
  Dir.glob(locales_glob).sort.each do |path|
    raw = File.read(path)
    data = Psych.safe_load(raw, permitted_classes: [Symbol], aliases: true)
    next unless data.is_a?(Hash)

    data.each do |locale_key, tree|
      next unless tree.is_a?(Hash)

      lk = locale_key.to_s
      merged_by_locale[lk] = deep_merge(merged_by_locale[lk], tree)
    end
  end
  merged_by_locale
end

def flatten_leaves(obj, prefix = "")
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
        out.merge!(flatten_leaves(v, p))
      else
        out[p] = v
      end
    end
  else
    out[prefix] = obj
  end
  out
end

def all_key_paths(obj, prefix = "")
  paths = []
  return paths unless obj.is_a?(Hash)

  obj.each do |k, v|
    p = prefix.empty? ? k.to_s : "#{prefix}.#{k}"
    paths << p
    paths.concat(all_key_paths(v, p)) if v.is_a?(Hash) && !v.empty?
  end
  paths
end

def stable_value_repr(v)
  case v
  when Hash, Array
    Psych.dump(v).strip
  else
    v.inspect
  end
end

def diff_locales(base_label, compare_label, base_trees, compare_trees)
  locales = (base_trees.keys | compare_trees.keys).sort
  found_diff = false

  locales.each do |locale|
    a = base_trees[locale] || {}
    b = compare_trees[locale] || {}

    paths_a = all_key_paths(a).to_set
    paths_b = all_key_paths(b).to_set
    only_a = paths_a - paths_b
    only_b = paths_b - paths_a

    leaves_a = flatten_leaves(a)
    leaves_b = flatten_leaves(b)
    keys_only_a = leaves_a.keys - leaves_b.keys
    keys_only_b = leaves_b.keys - leaves_a.keys
    value_changes = (leaves_a.keys & leaves_b.keys).reject { |k| leaves_a[k] == leaves_b[k] }

    next if only_a.empty? && only_b.empty? && keys_only_a.empty? && keys_only_b.empty? && value_changes.empty?
    found_diff = true

    puts "=" * 72
    puts "Locale: #{locale}"
    puts "  BASE = #{base_label}  |  COMPARE = #{compare_label}"
    puts "=" * 72

    unless only_a.empty? && only_b.empty?
      puts "\n## Structural key paths (nested hash keys; intermediate + leaf namespaces)"
      puts "\n  Only on BASE (#{base_label}) (#{only_a.size}):"
      only_a.sort.each { |p| puts "    - #{p}" }
      puts "\n  Only on COMPARE (#{compare_label}) (#{only_b.size}):"
      only_b.sort.each { |p| puts "    + #{p}" }
    end

    unless keys_only_a.empty? && keys_only_b.empty?
      puts "\n## Leaf translation keys (dot paths to scalar / empty-hash / array leaves)"
      puts "\n  Only on BASE (#{base_label}) (#{keys_only_a.size}):"
      keys_only_a.sort.each { |k| puts "    - #{k}" }
      puts "\n  Only on COMPARE (#{compare_label}) (#{keys_only_b.size}):"
      keys_only_b.sort.each { |k| puts "    + #{k}" }
    end

    unless value_changes.empty?
      puts "\n## Same leaf key, different value (#{value_changes.size})"
      value_changes.sort.each do |k|
        puts "\n  #{k}"
        puts "    #{base_label}:    #{stable_value_repr(leaves_a[k])}"
        puts "    #{compare_label}: #{stable_value_repr(leaves_b[k])}"
      end
    end

    puts ""
  end

  found_diff
end

base_ref, compare_ref, cli_rails_root, app_subdir = parse_args(ARGV)
rails_root = resolve_rails_root(cli_rails_root, app_subdir)
git_root = git_root_for_rails_app(rails_root)
locales_dir = File.join(rails_root, "config", "locales")
abort "Missing locales directory: #{locales_dir}" unless File.directory?(locales_dir)

locales_glob = File.join(locales_dir, "**", "*.yml")

puts "Rails root:  #{rails_root}"
puts "Git root:    #{git_root}"
puts "Locale glob: #{locales_glob}"
puts ""

ensure_clean_tree!(git_root)
abort("Unknown git ref: #{base_ref}") unless ref_exists?(git_root, base_ref)

compare_ref = compare_ref || git_capture(git_root, "rev-parse", "HEAD")
abort("Could not resolve default --compare (HEAD)") if compare_ref.empty?
abort("Unknown git ref: #{compare_ref}") unless ref_exists?(git_root, compare_ref)

was = current_branch(git_root)
was ||= git_capture(git_root, "rev-parse", "HEAD")

puts "Collecting merged locale YAML from BASE ref:    #{base_ref}"
checkout!(git_root, base_ref)
base_trees = load_all_locale_yamls(locales_glob)

puts "Collecting merged locale YAML from COMPARE ref: #{compare_ref}"
checkout!(git_root, compare_ref)
compare_trees = load_all_locale_yamls(locales_glob)

puts "Restoring previous HEAD: #{was}"
checkout!(git_root, was)

puts "\n"
found_diff = diff_locales(base_ref, compare_ref, base_trees, compare_trees)
unless found_diff
  puts "No merged locale YAML differences found between #{base_ref} and #{compare_ref}."
end
puts "Done."
