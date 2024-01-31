# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for linting CLs."""

from collections import OrderedDict
import itertools
import json
from typing import Any, Dict, Generator, List, Optional, Set

from RECIPE_MODULES.chromeos.gerrit.api import PatchSet

from PB.chromite.api.depgraph import ListRequest
from PB.chromite.api.depgraph import SourcePath
from PB.chromite.api.toolchain import LinterFinding
from PB.chromite.api.toolchain import LinterRequest
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.go.chromium.org.luci.buildbucket.proto.common import SUCCESS
from PB.recipe_engine.result import RawResult
from PB.recipes.chromeos.build_linters import BuildLintersProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import RecipeApi
from recipe_engine.recipe_api import StepFailure
from recipe_engine.recipe_test_api import RecipeTestApi
from recipe_engine.recipe_test_api import TestData

DEPS = [
    'recipe_engine/path',
    'recipe_engine/step',
    'recipe_engine/tricium',
    'build_menu',
    'chrome',
    'chromite',
    'cros_build_api',
    'cros_sdk',
    'cros_source',
    'gerrit',
    'repo',
    'src_state',
]


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

    output_data = {}
    for linter, files_by_patchset in relevant_patchsets.items():
      files = sorted(itertools.chain.from_iterable(files_by_patchset.values()))
      output_data[linter] = files
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


def _SyncChromeSources(api, config):
  """Sync chrome sources and configure Goma.

  Normally this would be handled by the install packages step for CQ, but this
  recipe does not call that so we call the logic directly.
  """
  with api.step.nest('Sync Chrome sources'):
    chrome_root = api.path['start_dir'].join('chrome')
    api.chrome.cache_sync(cache_path=chrome_root, sync=False,
                          step_name='populate chrome cache')
    api.chrome.sync(chrome_root, api.cros_sdk.chroot,
                    api.build_menu.sysroot.build_target, config.chrome.internal,
                    cache_dir=chrome_root.join('chrome_cache'))
    api.cros_sdk.set_chrome_root(chrome_root)
    api.cros_sdk.configure_goma()


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
  failing_build_exception = None
  result = None

  try:
    all_linter_output = []
    packages_detected = False
    chrome_synced = False

    api.build_menu.bootstrap_sysroot(config)
    for linter, patchsets in relevant_patchsets_by_linter.items():
      if not patchsets:
        continue
      affected_packages = _GetAffectedPackages(api, linter, patchsets)
      if not affected_packages:
        continue
      if not packages_detected:
        # Only do this once
        api.cros_source.ensure_synced_cache(
            projects=['chromiumos/chromite'],
            cache_path_override=api.src_state.workspace_path)
        packages_detected = True
      if not chrome_synced:
        _SyncChromeSources(api, config)
        chrome_synced = True
      linter_output = _GetLints(api, linter, affected_packages)
      all_linter_output.extend(linter_output)
    if packages_detected:
      comment_count = _WriteComments(api, all_linter_output)
      if comment_count:
        result = RawResult(
            status=SUCCESS,
            summary_markdown='Wrote %d findings.' % comment_count)
    else:
      result = RawResult(status=SUCCESS,
                         summary_markdown='No packages affected by changes.')
  except StepFailure as sf:
    # If we catch an exception, swallow it and store it so the next steps can
    # still occur; there is value in uploading the artifact even
    # in cases of build failure for debug purposes.
    failing_build_exception = sf
  try:
    api.build_menu.upload_artifacts(
        config, ignore_breakpad_symbol_generation_errors=failing_build_exception
        is not None)
  except StepFailure as sf:
    # If upload_artifacts threw an exception, surface that exception unless
    # build_and_test_images above threw an exception, in which case we want to
    # surface *that* exception for accuracy in reporting the build (and it's
    # likely that upload artifacts failed as a result of those previous issues).
    raise failing_build_exception or sf

  # Now that upload_artifacts is done, surface any exceptions from earlier.
  if failing_build_exception:
    raise failing_build_exception  # pylint: disable=raising-bad-type

  return result


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
      {
          'project': 'fake-project',
          'path': 'src/foo',
          'upstream': 'refs/heads/fake-branch',
      },
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
      api.post_check(post_process.DoesNotRun, 'Sync Chrome sources'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      revision=None, cq=False)

  # No changes to relevant projects
  yield api.build_menu.test(
      'no-relevant-projects',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.DoesNotRun, 'get relevant files'),
      api.post_check(post_process.DoesNotRun, 'configure builder'),
      api.post_check(post_process.DoesNotRun, 'Sync Chrome sources'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      **BuildTestArgs(input_properties={'relevant_projects': []}))

  # No changes with Relevant extensions
  yield api.build_menu.test(
      'no-relevant-extensions',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.DoesNotRun, 'configure builder'),
      api.post_check(post_process.DoesNotRun, 'Sync Chrome sources'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
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
      api.post_check(post_process.DoesNotRun, 'Sync Chrome sources'),
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
      **BuildTestArgs())


  # Normal build with relevant changes
  yield api.build_menu.test(
      'one-change',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess, 'Sync Chrome sources'),
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
                                       data=project_info), **BuildTestArgs())


  # Multiple change lists with relevant changes
  yield api.build_menu.test(
      'multiple-changes',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess, 'Sync Chrome sources'),
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
      api.post_check(post_process.DoesNotRun, 'Sync Chrome sources'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for tidy'),
      api.post_check(post_process.DoesNotRun, 'get affected packages for iwyu'),
      api.post_check(post_process.DoesNotRun, 'linting packages with clippy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with golint'),
      api.post_check(post_process.DoesNotRun, 'linting packages with tidy'),
      api.post_check(post_process.DoesNotRun, 'linting packages with iwyu'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
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
          })),
      **BuildTestArgs(),
      status='FAILURE',
  )

  # CROS Build API failure in DependencyService.List
  yield api.build_menu.test(
      'get-packages-failure',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepFailure,
                     'get affected packages for clippy'),
      api.post_check(post_process.DoesNotRun, 'Sync Chrome sources'),
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
                                          'DependencyService/List', retcode=1),
      **BuildTestArgs(),
      status='FAILURE',
  )

  # CROS Build API failure in ToolchainService.EmergeWithLinting
  yield api.build_menu.test(
      'get-clipy-lints-failure',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess, 'Sync Chrome sources'),
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
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages for clippy',
                                       data=project_info),
      api.build_menu.set_build_api_return('linting packages with clippy',
                                          'ToolchainService/EmergeWithLinting',
                                          retcode=1),
      **BuildTestArgs(),
      status='FAILURE',
  )

  yield api.build_menu.test(
      'upload-failure',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess, 'Sync Chrome sources'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for clippy'),
      api.post_check(post_process.StepSuccess,
                     'get affected packages for golint'),
      api.post_check(post_process.StepSuccess, 'linting packages with clippy'),
      api.post_check(post_process.StepSuccess, 'linting packages with golint'),
      api.post_check(post_process.StepSuccess,
                     'write comments for linter findings'),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages for clippy',
                                       data=project_info),
      api.repo.project_infos_step_data('get affected packages for golint',
                                       data=project_info),
      api.build_menu.set_build_api_return(
          'upload artifacts.call artifacts service', 'ArtifactsService/Get',
          retcode=1), **BuildTestArgs(), status='INFRA_FAILURE')
