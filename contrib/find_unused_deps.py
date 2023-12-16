#!/usr/bin/env python3

# -*- coding: utf-8 -*-
# Copyright 2024 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Scriptydoo to find unused module dependencies.

Sample usage:
    ./find_unused_deps.py
...That's it! It should report all unused dependencies to stdout.
"""

import dataclasses
from pathlib import Path
import re
from typing import List


@dataclasses.dataclass
class Dependency:
  """All the important info about a dependency on a module.

  Attributes:
    alias: The name of the module, as it's used in the recipe. For example,
      'cros_sdk' or 'depot_gerrit'.
    recipes_project: The recipes project where the module is defined. For
      example, 'chromeos' or 'depot_tools'.
    module_name: The name of the module within recipes_project. For example,
      'gerrit'.
  """
  alias: str
  recipes_project: str
  module_name: str


def find_recipes_paths(root_dir: Path) -> List[Path]:
  """Find all recipe files within root_dir (recursively).

  If root_dir contains any examples/tests, those will be included.
  """
  recipes_paths: List[Path] = []
  for child in root_dir.iterdir():
    if child.is_dir():
      recipes_paths.extend(find_recipes_paths(child))
    elif child.suffix == '.py':
      with child.open() as f:
        lines = f.readlines()
      if any(line.startswith('def RunSteps') for line in lines):
        recipes_paths.append(child)
  return recipes_paths


def find_module_dirs(root_dir: Path) -> List[Path]:
  """Find all recipe modules within root_dir."""
  return [p for p in root_dir.iterdir() if (p / '__init__.py').exists()]


def find_unused_deps_in_recipe(recipe: Path) -> List[Dependency]:
  """Given a path to a recipe, find all unused dependencies in its DEPS."""
  deps = find_deps_in_file(recipe)
  unused_deps: List[Dependency] = []
  for dep in deps:
    if is_dep_unused_in_file(recipe, dep):
      unused_deps.append(dep)
  return unused_deps


def find_unused_deps_in_module(module: Path) -> List[Dependency]:
  """Given a path to a module dir, find all unused dependencies in its DEPS."""
  deps = find_deps_in_file(module / '__init__.py')
  unused_deps: List[Dependency] = []
  for dep in deps:
    is_dep_used = False
    for child in (module / 'test_api.py', module / 'api.py'):
      if not child.exists():
        continue
      if is_dep_used_in_file(child, dep):
        is_dep_used = True
        break
    if not is_dep_used:
      unused_deps.append(dep)
  return unused_deps


def find_deps_in_file(path: Path) -> List[Dependency]:
  """Parse DEPS from a file that should contain DEPS."""
  with path.open() as f:
    lines = f.readlines()
  deps_lines: List[str] = []
  for line in lines:
    if line.strip().startswith('#'):
      continue
    if line.startswith('DEPS = ') or deps_lines:
      deps_lines.append(line)
    if any(c in line for c in ']}') and deps_lines:
      break
  if not deps_lines:
    return []
  deps_as_one_line = ' '.join(deps_lines).strip()
  if '[' in deps_as_one_line and '{' in deps_as_one_line:
    raise ValueError(
        f'Unsure whether to parse DEPS as a list or dict: {deps_as_one_line}')
  if '[' in deps_as_one_line:
    return parse_deps_list(deps_as_one_line)
  if '{' in deps_as_one_line:
    return parse_deps_dict(deps_as_one_line)
  raise ValueError('Deps is neither a list nor a dict.')


def parse_deps_list(deps_line: str) -> List[Dependency]:
  """Parse a "DEPS = [...]" string, and return its Dependencies."""
  m = re.search(r'^DEPS = \s*\[([^\]]*)\]\s*$', deps_line)
  if m is None:
    raise ValueError(f'Failed to find list contents in line: {deps_line}')
  list_contents = m.group(1).split(',')
  deps: List[Dependency] = []
  for element in list_contents:
    if not element.strip():
      continue
    # Typical line:
    #   'depot_tools/gerrit',
    # This module's recipes_project is "depot_tools"; its module_name is
    # "gerrit"; and its alias is "gerrit".
    # Another example:
    #   'orch_menu',
    # This module's recipes_project is "chromeos"; its module_name is
    # "orch_menu"; and its alias is "orch_menu".
    element = element.strip().strip("'")
    if '/' in element:
      recipes_project, module_name = element.split('/')
    else:
      recipes_project, module_name = 'chromeos', element
    deps.append(
        Dependency(
            alias=module_name,
            recipes_project=recipes_project,
            module_name=module_name,
        ))
  return deps


def parse_deps_dict(deps_line: str) -> List[Dependency]:
  """Parse a "DEPS = {...}" string, and return its Dependencies."""
  m = re.search(r'^DEPS =\s*\{([^}]+)\}\s*$', deps_line)
  if m is None:
    raise ValueError(f'Failed to find dict contents in line: {deps_line}')
  dict_contents = m.group(1).split(',')
  deps: List[Dependency] = []
  for element in dict_contents:
    if not element.strip():
      continue
    # Typical line:
    #   'depot_gerrit': 'depot_tools/gerrit',
    # This module's recipes_project is "depot_tools"; its module_name is
    # "gerrit"; and its alias is "depot_gerrit".
    alias, path = element.split(':')
    alias = alias.strip().strip("'")
    path = path.strip().strip("'")
    if '/' in path:
      recipes_project, module_name = path.split('/')
    else:
      recipes_project, module_name = 'chromeos', path
    deps.append(
        Dependency(
            alias=alias,
            recipes_project=recipes_project,
            module_name=module_name,
        ))
  return deps


def is_dep_unused_in_file(path: Path, dep: Dependency) -> bool:
  """Return whether the dependency is unused in that file."""
  return not is_dep_used_in_file(path, dep)


def is_dep_used_in_file(path: Path, dep: Dependency) -> bool:
  """Return whether the dependency is used in that file."""
  with path.open() as f:
    lines = f.readlines()
  usage_regexes = (
      re.compile(fr'\bapi\.{dep.alias}'),
      re.compile(fr'\bm\.{dep.alias}'),
      # Some imports from other recipe modules require the module to be
      # initialized, such as time.exponential_retry. In practice, not _all_ such
      # imports actually require the module to be initialized, so we'll catch
      # some false positives here. But there doesn't seem to be a way to know
      # more rigorously without running.
      re.compile(
          fr'^from RECIPE_MODULES\.{dep.recipes_project}\.{dep.module_name}'
          '.*import'),
  )
  for line in lines:
    if any(regex.search(line) for regex in usage_regexes):
      return True
  return False


def main() -> None:
  """Find unused dependencies and report them."""
  total_unused_deps = 0

  recipes_paths = find_recipes_paths(Path('./recipes'))
  recipes_with_unused_deps: List[Path] = []
  for recipe in recipes_paths:
    unused_deps = find_unused_deps_in_recipe(recipe)
    if unused_deps:
      print(
          f'Recipe {recipe} has unused deps: {[d.alias for d in unused_deps]}')
      recipes_with_unused_deps.append(recipe)
      total_unused_deps += len(unused_deps)

  module_paths = find_module_dirs(Path('./recipe_modules'))
  modules_with_unused_deps: List[Path] = []
  for module in module_paths:
    unused_deps = find_unused_deps_in_module(module)
    if unused_deps:
      aliases = [d.alias for d in unused_deps]
      print(f'Module {module} has {len(unused_deps)} unused deps: {aliases}')
      modules_with_unused_deps.append(module)
      total_unused_deps += len(unused_deps)

  print()
  print(f'Number of recipes with unused deps: {len(recipes_with_unused_deps)}')
  print(f'Number of modules with unused deps: {len(modules_with_unused_deps)}')
  print(f'Total unused dependencies: {total_unused_deps}')


if __name__ == '__main__':
  main()
