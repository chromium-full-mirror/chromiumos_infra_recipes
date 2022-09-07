# -*- coding: utf-8 -*-
# Copyright 2022 The ChromiumOS Authors.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for updating libchrome-version.eclass"""

DEPS = [
    'build_menu',
    'cros_source',
    'src_state',
    'git',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/step',
    'repo',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

_LIBCHROME_ECLASS_PATH = 'eclass/libchrome-version.eclass'


def get_latest_version(api, project_dir, pkg_group, pkg_name):
  files = api.file.listdir(
      'list %s ebuilds' % (pkg_name), project_dir.join(pkg_group, pkg_name),
      test_data=[
          'files',
          'libchrome-9999.ebuild',
          'libbrillo-9999.ebuild',
          'libchrome-0.0.1-r1234.ebuild',
          'libbrillo-0.0.1-r5678.ebuild',
      ])
  stable_ebuild_prefix = '%s-0.0.1-r' % (pkg_name)
  stable_ebuild_suffix = '.ebuild'
  stable_ebuilds = [
      f.pieces[-1]
      for f in files
      if f.pieces[-1].startswith(stable_ebuild_prefix)
  ]
  stable_ebuild = stable_ebuilds[0]
  return int(
      stable_ebuild[len(stable_ebuild_prefix):-len(stable_ebuild_suffix)])


def update_eclass(api, project_dir, pkg_group, pkg_name):
  with api.step.nest('update for %s/%s' % (pkg_group, pkg_name)):
    pkg_ebuild_revision = get_latest_version(api, project_dir, pkg_group,
                                             pkg_name)
    api.step('update eclass', [
        'sed', '-i',
        's/^REQUIRED_%s_EBUILD_VERSION.*/REQUIRED_%s_EBUILD_VERSION=%d/g' %
        (pkg_name.upper(), pkg_name.upper(), pkg_ebuild_revision),
        _LIBCHROME_ECLASS_PATH
    ])


def RunSteps(api):
  commit = api.src_state.gitiles_commit
  if not commit.project:
    commit = api.src_state.internal_manifest.as_gitiles_commit_proto

  with api.build_menu.configure_builder(disable_sdk=True, missing_ok=True,
                                        commit=commit):
    with api.build_menu.setup_workspace():
      project_dir = api.cros_source.workspace_path.join(
          'src/third_party/chromiumos-overlay')
      with api.context(cwd=project_dir):
        project_info = api.repo.project_info()
        with api.step.nest('update libchrome-version.eclass'):
          update_eclass(api, project_dir, 'chromeos-base', 'libchrome')
          update_eclass(api, project_dir, 'chromeos-base', 'libbrillo')
          api.file.read_text('display new eclass',
                             project_dir.join(_LIBCHROME_ECLASS_PATH))
          api.git.add([_LIBCHROME_ECLASS_PATH])

        if api.git.get_working_dir_diff_files():
          api.git.commit(
              'Update minimum required libchrome/libbrillo revision\n\nBUG=None\nTEST=None'
          )
          api.git.push(
              project_info.remote,
              # TODO(fqj): change to %submit once stablized.
              'HEAD:refs/for/main%r=fqj@google.com,r=hscham@chromium.org,l=Commit-Queue+1',
              dry_run=api.build_menu.is_staging)


def GenTests(api):
  yield api.test('script-success')
