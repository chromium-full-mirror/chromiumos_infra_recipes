# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for linting CLs with Cargo Clippy."""

from collections import OrderedDict
import json

from PB.chromite.api.depgraph import ListRequest, SourcePath
from PB.chromite.api.toolchain import LinterRequest, LinterFinding
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange, SUCCESS
from PB.recipes.chromeos.build_linters import BuildLintersProperties
from PB.recipe_engine.result import RawResult

from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

DEPS = [
    'recipe_engine/step',
    'recipe_engine/swarming',
    'recipe_engine/tricium',
    'build_menu',
    'chromite',
    'cros_build_api',
    'cros_source',
    'gerrit',
    'repo',
    'src_state',
    'test_util',
    'workspace_util',
]

PROPERTIES = BuildLintersProperties


def _GetRelevantPatchsets(api, properties):
  """Returns a map of files with relevant extensions grouped by patchset."""
  with api.step.nest('get relevant patches') as presentation:
    relevant_extensions = ['rs']
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
    relevant_files = {}
    for patch_set in patch_sets:
      relevant_for_patchset = [
          filepath for filepath in patch_set.file_infos.keys()
          if filepath.split('.')[-1] in relevant_extensions
      ]
      if relevant_for_patchset:
        relevant_files[patch_set] = relevant_for_patchset
    all_files = set(f for files in relevant_files.values() for f in files)
    presentation.logs['output'] = sorted(all_files)
    result_count = len(all_files)
    presentation.step_text = 'found %d modified relevant files' % result_count
    return relevant_files


def _GetSourcePaths(api, relevant_patchsets):
  """Returns Sourcepath protos with project paths prepended to filepaths."""
  source_paths = []
  for patch_set, filepaths in relevant_patchsets.items():
    for project_path in api.cros_source.find_project_paths(
        patch_set.project, patch_set.branch):
      for filepath in filepaths:
        source_paths.append(SourcePath(path='%s/%s' % (project_path, filepath)))
  return source_paths


def _GetAffectedPackages(api, relevant_patchsets):
  """Get a list of packages affected by changes to some list of files."""
  with api.step.nest('get affected packages') as presentation:
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


def _GetLints(api, affected_packages):
  """Emerges affected packages and retrieves generated lints."""
  with api.step.nest('linting packages'):
    test_data = json.dumps({
        'findings': [{
            'message': 'test message',
            'locations': [{
                'filepath': 'path/file.rs',
                'line_start': 1,
                'line_end': 1
            }],
            'linter': LinterFinding.Linters.CARGO_CLIPPY
        }]
    })
    return api.cros_build_api.ToolchainService.EmergeWithLinting(
        LinterRequest(packages=affected_packages,
                      sysroot=api.build_menu.sysroot,
                      chroot=api.build_menu.chroot),
        test_output_data=test_data).findings


def _WriteComments(api, findings):
  """Write comments with Tricium for linter findings."""
  with api.step.nest('write comments for linter findings') as presentation:
    comment_count = 0
    category_names = {
        LinterFinding.Linters.LINTER_UNSPECIFIED: 'BuildLinters',
        LinterFinding.Linters.CLANG_TIDY: 'ClangTidy',
        LinterFinding.Linters.CARGO_CLIPPY: 'CargoClippy',
    }
    for finding in findings:
      for location in finding.locations:
        comment_count += 1
        api.tricium.add_comment(category_names[finding.linter], finding.message,
                                location.filepath,
                                start_line=location.line_start,
                                end_line=location.line_start + 1)
    presentation.step_text = 'Wrote %d ' % comment_count
  api.tricium.write_comments()
  return comment_count


def RunSteps(api, properties):
  relevant_patchsets = _GetRelevantPatchsets(api, properties)
  if not relevant_patchsets:
    return RawResult(status=SUCCESS,
                     summary_markdown='No changes need linting.')
  with api.build_menu.configure_builder() as config:
    # We checkout the changes directly rather than using cherry pick
    # to ensure that line numbers are accurate for comments (see b/196275805).
    with api.build_menu.setup_workspace_and_chroot(cherry_pick_changes=False):
      return DoRunSteps(api, config, relevant_patchsets, properties)


def DoRunSteps(api, config, relevant_patchsets, _properties):
  api.build_menu.setup_sysroot_and_determine_relevance()
  try:
    api.build_menu.bootstrap_sysroot(config)
    affected_packages = _GetAffectedPackages(api, relevant_patchsets)
    if not affected_packages:
      return RawResult(status=SUCCESS,
                       summary_markdown='No packages affected by changes.')
    api.cros_source.ensure_synced_cache(
        projects=['chromiumos/chromite'],
        cache_path_override=api.src_state.workspace_path)
    linter_output = _GetLints(api, affected_packages)
    comment_count = _WriteComments(api, linter_output)
    if comment_count:
      return RawResult(status=SUCCESS,
                       summary_markdown='Wrote %d findings.' % comment_count)
  except StepFailure:
    raise
  finally:
    api.build_menu.upload_artifacts(config)


def GenTests(api):
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
                  'bar.rs': {}
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
                  'bar2.rs': {}
              }
          }
      }
  })

  project_info = [
      dict(project='fake-project', path='src/foo',
           upstream='refs/heads/fake-branch')
  ]

  def BuildTestArgs(**kwargs):
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
      api.post_check(post_process.DoesNotRun, 'linting packages'),
      api.post_check(post_process.StatusSuccess), revision=None, cq=False)

  # No changes to relevant projects
  yield api.build_menu.test(
      'no-relevant-projects',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.DoesNotRun, 'get relevant files'),
      api.post_check(post_process.DoesNotRun, 'configure builder'),
      api.post_check(post_process.DoesNotRun, 'linting packages'),
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
      api.post_check(post_process.DoesNotRun, 'linting packages'),
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
      api.post_check(post_process.StepSuccess, 'get affected packages'),
      api.post_check(post_process.DoesNotRun, 'linting packages'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages',
                                       data=project_info),
      api.build_menu.set_build_api_return('get affected packages',
                                          'DependencyService/List', data='{}'),
      api.post_check(post_process.StatusSuccess), **BuildTestArgs())

  # Normal build with relevant changes
  yield api.build_menu.test(
      'one-change',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess, 'get affected packages'),
      api.post_check(post_process.StepSuccess, 'linting packages'),
      api.post_check(post_process.StepSuccess,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages',
                                       data=project_info),
      api.post_check(post_process.StatusSuccess), **BuildTestArgs())

  # Multiple change lists with relevant changes
  yield api.build_menu.test(
      'multiple-changes',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess, 'get affected packages'),
      api.post_check(post_process.StepSuccess, 'linting packages'),
      api.post_check(post_process.StepSuccess,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess),
      api.repo.project_infos_step_data('get affected packages',
                                       data=project_info),
      api.repo.project_infos_step_data('get affected packages',
                                       data=project_info, iteration=2),
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
      api.post_check(post_process.StepFailure, 'get affected packages'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.StatusFailure),
      api.repo.project_infos_step_data('get affected packages',
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
      api.post_check(post_process.StepFailure, 'get affected packages'),
      api.post_check(post_process.DoesNotRun, 'linting packages'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages',
                                       data=project_info),
      api.build_menu.set_build_api_return('get affected packages',
                                          'DependencyService/List', retcode=1),
      **BuildTestArgs())

  # CROS Build API failure in ToolchainService.EmergeWithLinting
  yield api.build_menu.test(
      'get-clipy-lints-failure',
      api.post_check(post_process.StepSuccess, 'get relevant patches'),
      api.post_check(post_process.StepSuccess, 'get relevant files'),
      api.post_check(post_process.StepSuccess, 'get affected packages'),
      api.post_check(post_process.StepFailure, 'linting packages'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.gerrit.set_gerrit_fetch_changes_response('get relevant patches',
                                                   changes[:1], relevant_edits),
      api.repo.project_infos_step_data('get affected packages',
                                       data=project_info),
      api.build_menu.set_build_api_return('linting packages',
                                          'ToolchainService/EmergeWithLinting',
                                          retcode=1), **BuildTestArgs())
