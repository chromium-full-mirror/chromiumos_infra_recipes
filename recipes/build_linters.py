# -*- coding: utf-8 -*-
# Copyright 2021 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for linting CLs with Cargo Clippy."""

import json

from PB.chromite.api.depgraph import ListRequest, SourcePath
from PB.chromite.api.toolchain import LinterRequest
from PB.go.chromium.org.luci.buildbucket.proto.common import GerritChange
from PB.recipes.chromeos.build_linters import BuildLintersProperties
from recipe_engine import post_process
from recipe_engine.recipe_api import StepFailure

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
    'test_util',
    'workspace_util',
]

# TODO(crbug/1099259): Drop our properties.
# Our properties are processed and used by both the build_menu module, as well
# as various downstream dashboards and other consumers of buildbucket output
# properties.  They are not used directly within the recipe.
PROPERTIES = BuildLintersProperties


def _ChangesRelevant(api, properties):
  """Returns whether changes contain Rust and are in relevant repository."""
  with api.step.nest('check for relevant changes') as presentation:
    gerrit_changes = api.src_state.gerrit_changes
    if not gerrit_changes:
      presentation.status = api.step.FAILURE
      presentation.step_text = 'No changes given: Build is POINTLESS.'
      return False

    for commit in gerrit_changes:
      patchset = api.gerrit.fetch_patch_set_from_change(commit,
                                                        include_files=True)
      if patchset.project in properties.relevant_projects:
        if any(filename.endswith('.rs') for filename in patchset.file_infos):
          presentation.step_text = 'Found relevant changes'
          return True
    presentation.step_text = 'No relevant changes'
    return False


def _GetRustFiles(api):
  """Returns a list of rust files with changes in provided CL."""
  with api.step.nest('get rust files') as presentation:
    with api.step.nest('get patch sets'):
      patch_sets = [
          api.gerrit.fetch_patch_set_from_change(commit, include_files=True)
          for commit in api.src_state.gerrit_changes
      ]
    rust_files = []
    with api.step.nest('filter rust files'):
      for patch_set in patch_sets:
        src_paths = api.cros_source.find_project_paths(patch_set.project,
                                                       patch_set.branch)
        for src_path in src_paths:
          for path in patch_set.file_infos.keys():
            if path.endswith('.rs'):
              rust_file_path = SourcePath()
              rust_file_path.path = '%s/%s' % (src_path, path)
              rust_files.append(rust_file_path)
    presentation.logs['output'] = [str(rust_files)]
    presentation.step_text = 'found %d Rust changes.' % len(rust_files)
    return list(rust_files)


def _GetAffectedPackages(api, filepaths):
  """Get a list of packages affected by changes to some list of files."""
  with api.step.nest('get affected packages'):
    return api.cros_build_api.DependencyService.List(
        ListRequest(sysroot=api.build_menu.sysroot,
                    chroot=api.build_menu.chroot,
                    src_paths=filepaths)).package_deps


def _ClippyLintPackages(api, affected_packages):
  """Emerges affected packages and retrieves generated lints."""
  with api.step.nest('getting rust lints'):
    test_data = json.dumps({
        'findings': [{
            'message':
                'test message',
            'locations': [{
                'filepath': 'path/file.rs',
                'line_start': 1,
                'line_end': 1
            }]
        }]
    })
    return api.cros_build_api.ToolchainService.GetClippyLints(
        LinterRequest(packages=affected_packages,
                      sysroot=api.build_menu.sysroot,
                      chroot=api.build_menu.chroot),
        test_output_data=test_data).findings


def _WriteComments(api, findings):
  """Write comments with Tricium for linter findings."""
  with api.step.nest('write comments for linter findings') as presentation:
    comment_count = 0
    for finding in findings:
      for location in finding.locations:
        comment_count += 1
        api.tricium.add_comment('CargoClippy', finding.message,
                                location.filepath,
                                start_line=location.line_start,
                                end_line=location.line_start)
    presentation.step_text = 'Wrote %d ' % comment_count
  api.tricium.write_comments()


def RunSteps(api, properties):
  if not _ChangesRelevant(api, properties):
    return None
  with api.build_menu.configure_builder() as config:
    with api.build_menu.setup_workspace_and_chroot():
      return DoRunSteps(api, config, properties)


def DoRunSteps(api, config, _properties):
  api.build_menu.setup_sysroot_and_determine_relevance()
  failing_build = False
  try:
    api.build_menu.bootstrap_sysroot(config)
    rust_files = _GetRustFiles(api)
    affected_packages = _GetAffectedPackages(api, rust_files)
    api.cros_source.ensure_synced_cache(
        projects=['chromiumos/chromite'],
        cache_path_override=api.src_state.workspace_path)
    findings = _ClippyLintPackages(api, affected_packages)
    _WriteComments(api, findings)
  except StepFailure:
    failing_build = True
    raise
  finally:
    api.build_menu.upload_artifacts(config, failing_build=failing_build)


def GenTests(api):
  changes = [
      GerritChange(host='chromium-review.googlesource.com', change=1,
                   project='fake-project', patchset=1),
      GerritChange(host='chromium-review.googlesource.com', change=2,
                   project='fake-project', patchset=2),
  ]

  rust_edits = {
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
  }

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
      api.post_check(post_process.StepFailure, 'check for relevant changes'),
      api.post_check(post_process.DoesNotRun, 'configure builder'),
      api.post_check(post_process.StatusSuccess), revision=None, cq=False)

  # No changes to relevant projects
  yield api.build_menu.test(
      'no-relevant-projects',
      api.post_check(post_process.StepSuccess, 'check for relevant changes'),
      api.post_check(post_process.DoesNotRun, 'configure builder'),
      api.gerrit.set_gerrit_fetch_changes_response('check for relevant changes',
                                                   changes[:1], rust_edits),
      api.post_check(post_process.StatusSuccess),
      **BuildTestArgs(input_properties={'relevant_projects': []}))

  # No changes with Rust
  yield api.build_menu.test(
      'no-relevant-changes',
      api.post_check(post_process.StepSuccess, 'check for relevant changes'),
      api.post_check(post_process.DoesNotRun, 'get rust files'),
      api.post_check(post_process.DoesNotRun, 'getting rust lints'),
      api.post_check(post_process.StatusSuccess),
      api.gerrit.set_gerrit_fetch_changes_response(
          'check for relevant changes', changes[:1], {
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
          }), **BuildTestArgs())

  # Normal build with rust changes
  yield api.build_menu.test(
      'one-change',
      api.post_check(post_process.StepSuccess, 'check for relevant changes'),
      api.post_check(post_process.StepSuccess, 'get rust files'),
      api.post_check(post_process.StepSuccess, 'getting rust lints'),
      api.post_check(post_process.StepSuccess,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.gerrit.set_gerrit_fetch_changes_response('check for relevant changes',
                                                   changes[:1], rust_edits),
      api.gerrit.set_gerrit_fetch_changes_response(
          'get rust files.get patch sets', changes[:1], rust_edits),
      api.repo.project_infos_step_data('get rust files.filter rust files',
                                       data=project_info),
      api.post_check(post_process.StatusSuccess), **BuildTestArgs())

  # Multiple change lists with rust changes
  yield api.build_menu.test(
      'multiple-changes',
      api.post_check(post_process.StepSuccess, 'check for relevant changes'),
      api.post_check(post_process.MustRun, 'get rust files.filter rust files'),
      api.post_check(post_process.StepSuccess, 'get rust files'),
      api.post_check(post_process.StepSuccess, 'getting rust lints'),
      api.post_check(post_process.StepSuccess,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusSuccess),
      api.repo.project_infos_step_data('get rust files.filter rust files',
                                       data=project_info),
      api.repo.project_infos_step_data('get rust files.filter rust files',
                                       data=project_info, iteration=2),
      api.gerrit.set_gerrit_fetch_changes_response('check for relevant changes',
                                                   [changes[0]], rust_edits),
      api.gerrit.set_gerrit_fetch_changes_response(
          'get rust files.get patch sets', [changes[0]], rust_edits),
      api.gerrit.set_gerrit_fetch_changes_response(
          'get rust files.get patch sets', [changes[1]], rust_edits,
          iteration=2), **BuildTestArgs(gerrit_changes=changes))

  # No source paths for project api.cros_source.find_project_paths
  edits_unknown_branch = {
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
  }
  yield api.build_menu.test(
      'no-source-path',
      api.post_check(post_process.StepSuccess, 'check for relevant changes'),
      api.post_check(post_process.StepFailure, 'get rust files'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.StatusFailure),
      api.repo.project_infos_step_data('get rust files.filter rust files',
                                       data=project_info),
      api.gerrit.set_gerrit_fetch_changes_response('check for relevant changes',
                                                   changes[:1],
                                                   edits_unknown_branch),
      api.gerrit.set_gerrit_fetch_changes_response(
          'get rust files.get patch sets', changes[:1], edits_unknown_branch),
      **BuildTestArgs())

  # CROS Build API failure in DependencyService.List
  yield api.build_menu.test(
      'get-packages-failure',
      api.post_check(post_process.StepSuccess, 'check for relevant changes'),
      api.post_check(post_process.StepFailure, 'get affected packages'),
      api.post_check(post_process.DoesNotRun, 'getting rust lints'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.gerrit.set_gerrit_fetch_changes_response(
          'get rust files.get patch sets', changes[:1], rust_edits),
      api.gerrit.set_gerrit_fetch_changes_response('check for relevant changes',
                                                   changes[:1], rust_edits),
      api.repo.project_infos_step_data('get rust files.filter rust files',
                                       data=project_info),
      api.build_menu.set_build_api_return('get affected packages',
                                          'DependencyService/List', retcode=1),
      **BuildTestArgs())

  # CROS Build API failure in ToolchainService.GetClippyLints
  yield api.build_menu.test(
      'get-clipy-lints-failure',
      api.post_check(post_process.StepSuccess, 'check for relevant changes'),
      api.post_check(post_process.StepFailure, 'getting rust lints'),
      api.post_check(post_process.DoesNotRun,
                     'write comments for linter findings'),
      api.post_check(post_process.MustRun, 'upload artifacts'),
      api.post_check(post_process.StatusFailure),
      api.gerrit.set_gerrit_fetch_changes_response(
          'get rust files.get patch sets', changes[:1], rust_edits),
      api.gerrit.set_gerrit_fetch_changes_response('check for relevant changes',
                                                   changes[:1], rust_edits),
      api.repo.project_infos_step_data('get rust files.filter rust files',
                                       data=project_info),
      api.build_menu.set_build_api_return('getting rust lints',
                                          'ToolchainService/GetClippyLints',
                                          retcode=1), **BuildTestArgs())
