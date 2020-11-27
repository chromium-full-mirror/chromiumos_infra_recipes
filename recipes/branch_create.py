# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Creates a branch using `cros branch create`."""

from PB.chromiumos.branch import Branch
from PB.recipes.chromeos.branch_create import CreateBranchProperties

DEPS = [
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/step',
    'recipe_engine/url',
    'depot_tools/gitiles',
    'cros_branch',
    'cros_source',
]

PROPERTIES = CreateBranchProperties


def RunSteps(api, properties):
  with api.step.nest("fetch manifest"):
    if not properties.manifest.filename:
      raise ValueError('manifest filename is required.')
    gitiles_commit = properties.manifest.gitiles_commit
    if not gitiles_commit.host:
      raise ValueError('manifest gitiles host is required.')
    if not gitiles_commit.project:
      raise ValueError('manifest gitiles project is required.')
    if not gitiles_commit.id and not gitiles_commit.ref:
      raise ValueError('manifest gitiles commit id or ref is required.')

    repo_url = api.gitiles.unparse_repo_url(gitiles_commit.host,
                                            gitiles_commit.project)
    repo_branch = gitiles_commit.id or gitiles_commit.ref

    manifest = api.gitiles.download_file(repo_url, properties.manifest.filename,
                                         repo_branch)

    # Path to download the manifest to.
    download_path = api.path.mkdtemp(prefix='manifests-').join('downloaded.xml')
    api.file.write_raw(
        name='write manifest to file', dest=download_path, data=manifest)

  # Run `cros branch create`.
  api.cros_branch.create_from_file(
      download_path,
      properties.branch_info,
      step_name='create branch',
      push=properties.push,
      force=properties.force)


def GenTests(api):
  yield api.test(
      'manifest-filename-missing',
      api.properties(manifest={}),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'manifest-gitiles-host-missing',
      api.properties(manifest={'filename': 'foo.xml'}),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'manifest-gitiles-project-missing',
      api.properties(manifest={
          'filename': 'foo.xml',
          'gitiles_commit': {
              'host': 'chromium.googlesource.com'
          }
      }),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'manifest-gitiles-id-ref-missing',
      api.properties(manifest={
          'filename': 'foo.xml',
          'gitiles_commit': {
              'host': 'chromium.googlesource.com',
              'project': 'manifest/internal'
          }
      }),
      api.expect_exception('ValueError'),
  )

  yield api.test(
      'manifest-valid',
      api.properties(
          manifest={
              'filename': 'foo.xml',
              'gitiles_commit': {
                  'host': 'chromium.googlesource.com',
                  'project': 'manifest/internal',
                  'ref': 'refs/head/main'
              }
          }, push=True, force=True, branch_info={
              'name': 'my_custom_branch',
              'descriptor': 'nami',
              'type': Branch.CUSTOM
          }),
      api.step_data('fetch manifest.fetch refs/head/main:foo.xml',
                    api.gitiles.make_encoded_file('foo')),
  )
