# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for linting CLs."""

from collections import OrderedDict
from typing import Any, Dict, Generator, List, Optional, Set
import json

from RECIPE_MODULES.chromeos.gerrit.api import PatchSet

from PB.chromite.api.depgraph import ListRequest, SourcePath
from PB.chromite.api.toolchain import LinterRequest, LinterFinding
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange, SUCCESS
from PB.recipes.chromeos.build_linters import BuildLintersProperties
from PB.recipe_engine.result import RawResult

from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/step',
    'recipe_engine/tricium',
    'build_menu',
    'chromite',
    'cros_build_api',
    'cros_source',
    'gerrit',
    'repo',
    'src_state',
]

PYTHON_VERSION_COMPATIBILITY = 'PY3'

PROPERTIES = BuildLintersProperties


def _GetRelevantPatchsetsByLinter(
    api: RecipeApi,
    properties: BuildLintersProperties) -> Dict[str, Dict[PatchSet, List[str]]]:
  """Get relevant patchsets, grouped by the linter they require.

  Returns:
    A map of files with relevant extensions grouped by required linter and
      patchset.
  """
  with api.step.nest('get relevant patches') as presentation:

    cpp_extensions = [
        'c', 'cc', 'cpp', 'cxx', 'c++', 'h', 'hh', 'hpp', 'hxx', 'h++'
    ]
    relevant_extensions = {
        'clippy': ['rs'],
        'golint': ['go'],
        'tidy': cpp_extensions,
        # FIXME(b/260476356): Temporarily disabling IWYU so that we can enable
        # it in the Chromie API and then test it in build_linters with led
        'iwyu': [],
    }
    patch_sets = [
        patchset for patchset in (
            api.gerrit.fetch_patch_set_from_change(commit, include_files=True)
            for commit in api.src_state.gerrit_changes)
        if patchset.project in properties.relevant_projects
    ]

    presentation.step_text = 'found %d relevant patchsets' % len(patch_sets)
    if not patch_sets:
      return {}

  with api.step.nest('get relevant files') as presentation:
    relevant_patchsets = {}
    for linter, extensions in relevant_extensions.items():
      relevant_patchsets[linter] = {}
      for patch_set in patch_sets:
        relevant_for_patchset = [
            filepath for filepath in patch_set.file_infos.keys()
            if filepath.split('.')[-1] in extensions
        ]
        if relevant_for_patchset:
          relevant_patchsets[linter][patch_set] = relevant_for_patchset

    output_data = {
        linter: sorted(f for files in relevant_patchsets[linter].values()
                       for f in files) for linter in relevant_extensions.keys()
    }
    presentation.logs['output'] = json.dumps(output_data, sort_keys=True)
    if any(len(files) for files in output_data.values()):
      presentation.step_text = 'found relevant files'
    else:
      presentation.step_text = 'found no relevant files'
    return relevant_patchsets


def _GetSourcePaths(
    api: RecipeApi,
    relevant_patchsets: Dict[str, Dict[PatchSet,
                                       List[str]]]) -> List[SourcePath]:
  """Returns Sourcepath protos with project paths prepended to filepaths."""
  source_paths = []
  for patch_set, filepaths in relevant_patchsets.items():
    for project_path in api.cros_source.find_project_paths(
        patch_set.project, patch_set.branch):
      for filepath in filepaths:
        source_paths.append(SourcePath(path='%s/%s' % (project_path, filepath)))
  return source_paths


def _GetAffectedPackages(
    api: RecipeApi, linter: str,
    relevant_patchsets: Dict[str, Dict[PatchSet,
                                       List[str]]]) -> List[PackageInfo]:
  """Get a list of packages affected by changes to some list of files."""
  with api.step.nest('get affected packages for %s' % linter) as presentation:
    source_paths = _GetSourcePaths(api, relevant_patchsets)
    source_paths.sort(key=lambda x: x.path)
    affected = api.cros_build_api.DependencyService.List(
        ListRequest(sysroot=api.build_menu.sysroot,
                    chroot=api.build_menu.chroot,
                    src_paths=source_paths)).package_deps
    if not affected:
      presentation.step_text = 'No packages affected for target platform'
    else:
      presentation.step_text = 'Found %d affected packages' % len(affected)
    return affected


def _GetLints(api: RecipeApi, linter: str,
              affected_packages: Set[PackageInfo]) -> List[LinterFinding]:
  """Emerges affected packages and retrieves generated lints."""
  with api.step.nest('linting packages with %s' % linter):
    linters = {
        'tidy': LinterFinding.Linters.CLANG_TIDY,
        'clippy': LinterFinding.Linters.CARGO_CLIPPY,
        'golint': LinterFinding.Linters.GO_LINT,
        'iwyu': LinterFinding.Linters.IWYU,
    }
    enabled_linter = linters[linter]

    test_findings = [{
        'message': 'test message',
        'locations': [{
            'filepath': 'path/file.rs',
            'line_start': 1,
            'line_end': 1
        }],
        'linter': LinterFinding.Linters.CARGO_CLIPPY
    }, {
        'message': 'test message',
        'locations': [{
            'filepath': 'path/file.go',
            'line_start': 1,
            'line_end': 1
        }],
        'linter': LinterFinding.Linters.GO_LINT
    }, {
        'message': 'test message',
        'locations': [{
            'filepath': 'path/file.cpp',
            'line_start': 1,
            'line_end': 1
        }],
        'linter': LinterFinding.Linters.CLANG_TIDY
    }, {
        'message': 'test message',
        'locations': [{
            'filepath': '/build/atlas/usr/include/chromeos/file.cpp',
            'line_start': 1,
            'line_end': 1
        }],
        'linter': LinterFinding.Linters.CLANG_TIDY
    }, {
        'message': 'test message',
        'locations': [{
            'filepath': '/build/atlas/usr/include/chromeos/file.cpp',
            'line_start': 1,
            'line_end': 1
        }],
        'linter': LinterFinding.Linters.IWYU
    }]

    test_data = json.dumps(
        {
            'findings':
                [f for f in test_findings if f['linter'] == enabled_linter]
        }, sort_keys=True)

    disabled_linters = set(linters.values()) - set([enabled_linter])

    return api.cros_build_api.ToolchainService.EmergeWithLinting(
        LinterRequest(packages=affected_packages,
                      sysroot=api.build_menu.sysroot,
                      chroot=api.build_menu.chroot, filter_modified=False,
                      disabled_linters=disabled_linters),
        test_output_data=test_data).findings


def _WriteComments(api: RecipeApi, findings: List[LinterFinding]) -> int:
  """Write comments with Tricium for linter findings."""
  with api.step.nest('write comments for linter findings') as presentation:
    comment_count = 0
    ignored_count = 0
    category_names = {
        LinterFinding.Linters.LINTER_UNSPECIFIED: 'BuildLinters',
        LinterFinding.Linters.CLANG_TIDY: 'ClangTidy',
        LinterFinding.Linters.CARGO_CLIPPY: 'CargoClippy',
        LinterFinding.Linters.GO_LINT: 'Golint',
        LinterFinding.Linters.IWYU: 'Include What You Use',
    }
    for finding in findings:
      for location in finding.locations:
        if location.filepath.startswith('/'):
          ignored_count += 1
          continue
        comment_count += 1
        api.tricium.add_comment(category_names[finding.linter], finding.message,
                                location.filepath,
                                start_line=location.line_start,
                                end_line=location.line_start + 1)
    presentation.step_text = 'Wrote %d ' % comment_count
  api.tricium.write_comments()
  return comment_count


def RunSteps(api: RecipeApi,
             properties: BuildLintersProperties) -> Optional[RawResult]:
  relevant_patchsets_by_linter = _GetRelevantPatchsetsByLinter(api, properties)
  if not any(patches for patches in relevant_patchsets_by_linter.values()):
    return RawResult(status=SUCCESS,
                     summary_markdown='No changes need linting.')
  with api.build_menu.configure_builder() as config:
    # Unfortunately we must pick between two bugs. We can either:
    # 1) Checkout the changes directly rather than using cherry pick to ensure
    #   that line numbers are accurate for comments (see b/196275805).
    # 2) Cherry pick the changes to ensure that we're otherwise at TOT to
    #   prevent problems with dependencies not being in sync (see b/240481231)
    # Because the bug referenced in 2) is more common, we should cherry pick.
    with api.build_menu.setup_workspace_and_chroot(cherry_pick_changes=True):
      return DoRunSteps(api, config, relevant_patchsets_by_linter)


def DoRunSteps(  # pylint: disable=inconsistent-return-statements
    api: RecipeApi, config: BuilderConfig,
    relevant_patchsets_by_linter: Dict[str,
                                       Dict[PatchSet,
                                            List[str]]]) -> Optional[RawResult]:
  api.build_menu.setup_sysroot_and_determine_relevance()
  try:
    all_linter_output = []
    packages_detected = False

    # We need to iterate in sorted order to be deterministic in python2
    api.build_menu.bootstrap_sysroot(config)
    for linter in sorted(relevant_patchsets_by_linter.keys()):
      if not relevant_patchsets_by_linter[linter]:
        continue
      affected_packages = _GetAffectedPackages(
          api, linter, relevant_patchsets_by_linter[linter])
      if not affected_packages:
        continue
      if not packages_detected:
        # Only do this once
        api.cros_source.ensure_synced_cache(
            projects=['chromiumos/chromite'],
            cache_path_override=api.src_state.workspace_path)
        packages_detected = True
      linter_output = _GetLints(api, linter, affected_packages)
      all_linter_output.extend(linter_output)
    if not packages_detected:
      return RawResult(status=SUCCESS,
                       summary_markdown='No packages affected by changes.')
    comment_count = _WriteComments(api, all_linter_output)
    if comment_count:
      return RawResult(status=SUCCESS,
                       summary_markdown='Wrote %d findings.' % comment_count)
  finally:
    api.build_menu.upload_artifacts(config)


def GenTests(api: RecipeTestApi) -> Generator[TestData, None, None]:
  changes = [
      GerritChange(host='chromium-review.googlesource.com', change=1,
                   project='fake-project', patchset=1),
      GerritChange(host='chromium-review.googlesource.com', change=2,
                   project='fake-project', patchset=2),
  ]

  relevant_edits = OrderedDict({
      1: {
          'change_id': '1',
          'created': '2020-10-22 18:54:00.000000000',
          'branch': 'fake-branch',
          'revision_info': {
              '_number': 1,
              'ref': 'refs/change/foo',
              'files': {
                  'foo.rs': {},
                  'bar.rs': {},
                  'foo.go': {},
                  'bar.go': {},
              }
          }
      },
      2: {
          'change_id': '2',
          'created': '2020-10-22 18:54:00.000000000',
          'branch': 'fake-branch',
          'revision_info': {
              '_number': 2,
              'ref': 'refs/change/foo',
              'files': {
                  'foo.rs': {},
                  'bar2.rs': {},
                  'foo.go': {},
                  'bar2.go': {},
                  'foo.c': {},
                  '/build/atlas/usr/include/chromeos/bar.h': {},
              }
          }
      },
  })

  project_info = [
      dict(project='fake-project', path='src/foo',
           upstream='refs/heads/fake-branch')
  ]

  def BuildTestArgs(**kwargs: Any) -> Dict[str, Any]:
    """Generate kwargs for a test build."""
    kwargs.setdefault('cq', True)
    kwargs.setdefault('build_target', 'atlas')
    kwargs.setdefault('input_properties',
                      {'relevant_projects': ['fake-project']})
    kwargs.setdefault('gerrit_changes', changes[:1])
    return kwargs

  # No changes provided
  yield api.build_menu.test(
      'no-changes',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.DoesNotRun, 'get relevant files'),
      api.post_check(post_process.DoesNotRun, 'configure builder'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.post_check(post_process.StatusSuccess), revision=None, cq=False)

  # No changes to relevant projects
  yield api.build_menu.test(
      'no-relevant-projects',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.DoesNotRun, 'get relevant files'),
      api.post_check(post_process.DoesNotRun, 'configure builder'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.post_check(post_process.StatusSuccess),
      **BuildTestArgs(input_properties={'relevant_projects': []}))

  # No changes with Relevant extensions
  yield api.build_menu.test(
      'no-relevant-extensions',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.DoesNotRun, 'configure builder'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.post_check(post_process.StatusSuccess),
      api.gerrit.set_gerrit_fetch_changes_response(
          'get relevant patches', changes[:1],
          OrderedDict({
              1: {
                  'change_id': '1',
                  'created': '2020-10-22 18:54:00.000000000',
                  'branch': 'fake-branch',
                  'revision_info': {
                      '_number': 1,
                      'ref': 'refs/change/foo',
                      'files': {
                          'foo.ebuild': {},
                          'bar.sh': {}
                      }
                  }
              }
          })), **BuildTestArgs())

  # No affected packages relevant to target platform
  yield api.build_menu.test(
      'no-affected-packages',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for clippy'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for golint'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for tidy'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for iwyu'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages for clippy',
                                       data=project_info),
      api.build_menu.set_build_api_return('get affected packages for clippy',
                                          'DependencyService/List', data='{}'),
      api.repo.project_infos_step_data('get affected packages for golint',
                                       data=project_info),
      api.build_menu.set_build_api_return('get affected packages for golint',
                                          'DependencyService/List', data='{}'),
      api.post_check(post_process.StatusSuccess), **BuildTestArgs())

  # Normal build with relevant changes
  yield api.build_menu.test(
      'one-change',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for clippy'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for golint'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for tidy'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for iwyu'),
      api.post_check(post_process.StepSuccess, 'linting packages with clippy'),
      api.post_check(post_process.StepSuccess, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.post_check(post_process.StepSuccess,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages for clippy',
                                       data=project_info),
      api.repo.project_infos_step_data('get affected packages for golint',
                                       data=project_info),
      api.post_check(post_process.StatusSuccess), **BuildTestArgs())

  # Multiple change lists with relevant changes
  yield api.build_menu.test(
      'multiple-changes',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for clippy'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for golint'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for tidy'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for iwyu'),
      api.post_check(post_process.StepSuccess, 'linting packages with clippy'),
      api.post_check(post_process.StepSuccess, 'linting packages with golint'),
      api.post_check(post_process.StepSuccess, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.post_check(post_process.StepSuccess,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess),
      api.repo.project_infos_step_data('get affected packages for clippy',
                                       data=project_info),
      api.repo.project_infos_step_data('get affected packages for clippy',
                                       data=project_info, iteration=2),
      api.repo.project_infos_step_data('get affected packages for golint',
                                       data=project_info),
      api.repo.project_infos_step_data('get affected packages for golint',
                                       data=project_info, iteration=2),
      api.repo.project_infos_step_data('get affected packages for tidy',
                                       data=project_info),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   [changes[0]],
                                                   relevant_edits),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   [changes[1]], relevant_edits,
                                                   iteration=2),
      **BuildTestArgs(gerrit_changes=changes))

  # No source paths for project api.cros_source.find_project_paths
  yield api.build_menu.test(
      'no-source-path',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepFailure,
                     'get affected packages for clippy'),
      api.post_check(post_process.DoesNotRun,
                     'get affected packages for golint'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for tidy'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for iwyu'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.StatusFailure),
      api.repo.project_infos_step_data('get affected packages for clippy',
                                       data=project_info),
      api.gerrit.set_gerrit_fetch_changes_response(
          'get relevant patches', changes[:1],
          OrderedDict({
              1: {
                  'change_id': '1',
                  'created': '2020-10-22 18:54:00.000000000',
                  'branch': 'not-the-usual-fake-branch',
                  'revision_info': {
                      '_number': 1,
                      'ref': 'refs/change/foo',
                      'files': {
                          'foo.rs': {},
                          'bar.rs': {}
                      }
                  }
              }
          })), **BuildTestArgs())

  # CROS Build API failure in DependencyService.List
  yield api.build_menu.test(
      'get-packages-failure',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepFailure,
                     'get affected packages for clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages for clippy',
                                       data=project_info),
      api.build_menu.set_build_api_return('get affected packages for clippy',
                                          'DependencyService/List', retcode=1),
      **BuildTestArgs())

  # CROS Build API failure in ToolchainService.EmergeWithLinting
  yield api.build_menu.test(
      'get-clipy-lints-failure',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for clippy'),
      api.post_check(post_process.DoesNotRun,
                     'get affected packages for golint'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for tidy'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for iwyu'),
      api.post_check(post_process.StepFailure, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages for clippy',
                                       data=project_info),
      api.build_menu.set_build_api_return('linting packages with clippy',
                                          'ToolchainService/EmergeWithLinting',
                                          retcode=1), **BuildTestArgs())
