# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Creates a branch using `cros branch create`."""

from PB.chromiumos.branch import Branch
from PB.recipes.chromeos.branch_create import CreateBranchProperties

DEPS = [
    'recipe_engine/context',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/url',
    'cros_branch',
    'cros_source',
]

PROPERTIES = CreateBranchProperties


def RunSteps(api, properties):
  if not properties.manifest_url:
    raise ValueError('manifest URL is required.')

  # Validate the manifest URL. validate_url will throw a ValueError if the
  # string cannot be interpreted as a URL.
  api.url.validate_url(properties.manifest_url)

  # If the URL is valid, try to download it. If the HTTP request fails,
  # get_file will throw an HTTPError or an InfraHTTPError.

  # Path to download the manifest to.
  download_path = api.path.mkdtemp(prefix='manifests-').join('downloaded.xml')
  api.url.get_file(properties.manifest_url, download_path)

  api.cros_source.ensure_synced_cache()
  with api.cros_source.checkout_overlays_context(), api.context(
      cwd=api.cros_source.workspace_path):

    # Run `cros branch create`.
    api.cros_branch.create_from_file(
        download_path,
        properties.branch,
        step_name='create branch from manifest %s' % properties.manifest_url,
        push=properties.push,
        force=properties.force)


def GenTests(api):
  yield (api.test('url-missing') + api.expect_exception('ValueError'))

  yield (api.test('url-valid') + api.properties(
      manifest_url='http://www.chromium.org/manifest.xml',
      push=True,
      force=True,
      branch={
          'name': 'my_custom_branch',
          'descriptor': 'nami',
          'type': Branch.CUSTOM
      }))

  # We expect an HTTPError exception. That class doesn't have its name
  # set properly so we give expect_exception an empty string.
  yield (api.test('url-invalid') + api.url.error(
      'GET http://www.chromium.org/bad.xml',
      404) + api.properties(manifest_url='http://www.chromium.org/bad.xml') +
         api.expect_exception(''))

  yield (api.test('custom-no-name') + api.properties(
      manifest_url='http://www.chromium.org/manifest.xml',
      branch={'type': Branch.CUSTOM}) + api.expect_exception('ValueError'))

  yield (api.test('branch-type-unspecified') +
         api.properties(manifest_url='http://www.chromium.org/manifest.xml') +
         api.expect_exception('ValueError'))
