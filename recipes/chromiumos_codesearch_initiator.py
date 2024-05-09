# Copyright 2022 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Initialize ChromiumOS codesearch builders to create kzips.

Checks out chromiumos manifest repo and uses the latest snapshot commit hash
to initialize chromiumos codesearch builders.
"""

from typing import Any, Dict, Generator

from recipe_engine import post_process
from recipe_engine import recipe_api
from recipe_engine import recipe_test_api
from PB.recipes.chromeos.chromiumos_codesearch_initiator import (
    ChromiumosCodesearchInitiatorProperties)

DEPS = [
    'depot_tools/git',
    'recipe_engine/context',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/raw_io',
    'recipe_engine/scheduler',
]

PROPERTIES = ChromiumosCodesearchInitiatorProperties


def latest_ref_info(api: recipe_api.RecipeApi, clone_dir: str, repo: str,
                    branch: str):
  """Return the hash and timestamp of the latest commit on a branch."""
  clone_base_dir = api.context.cwd or api.path.cache_dir / 'builder'
  api.file.rmtree('Remove previous clone', clone_base_dir / clone_dir)
  with api.context(cwd=clone_base_dir):
    api.git('clone', '--depth=1', '-b', branch, repo, clone_dir,
            name='clone %s of %s' % (branch, repo))

  with api.context(cwd=clone_base_dir / clone_dir):
    commit_hash = api.git('rev-parse', 'HEAD', name='fetch hash',
                          stdout=api.raw_io.output_text()).stdout.strip()
    timestamp = api.git('log', '-1', '--format=%ct', 'HEAD',
                        name='fetch timestamp',
                        stdout=api.raw_io.output_text()).stdout.strip()

    return commit_hash, timestamp


def RunSteps(api: recipe_api.RecipeApi,
             properties: ChromiumosCodesearchInitiatorProperties) -> None:
  codesearch_dirname = '_'.join(properties.codesearch_repo.split('/')[-2:])
  mirror_hash, mirror_unix_timestamp = latest_ref_info(
      api, codesearch_dirname, properties.codesearch_repo, 'main')

  manifest_dirname = '_'.join(properties.manifest_repo.split('/')[-2:])
  manifest_hash, _ = latest_ref_info(api, manifest_dirname,
                                     properties.manifest_repo, 'snapshot')

  # Trigger the chromiumos_codesearch builders.
  child_properties: Dict[str, Any] = {
      'codesearch_mirror_revision': mirror_hash,
      'codesearch_mirror_revision_timestamp': mirror_unix_timestamp,
  }

  api.scheduler.emit_trigger(
      api.scheduler.GitilesTrigger(
          repo=properties.manifest_repo.removeprefix('https://'),
          ref='refs/heads/snapshot',
          revision=manifest_hash,
          properties=child_properties,
      ), project='chromeos', jobs=properties.child_jobs)


# TODO(crbug/1284439): Add more tests.
def GenTests(
    api: recipe_test_api.RecipeTestApi
) -> Generator[recipe_test_api.TestData, None, None]:
  yield api.test(
      'basic',
      api.properties(
          ChromiumosCodesearchInitiatorProperties(
              child_jobs=[
                  'amd64-generic-codesearch',
                  'arm64-generic-codesearch',
              ],
          ),
          codesearch_repo='https://chromium.googlesource.com/chromiumos/codesearch',
          manifest_repo='https://chromium.googlesource.com/chromiumos/manifest',
      ),
      api.post_check(
          post_process.MustRun,
          'clone snapshot of https://chromium.googlesource.com/chromiumos/manifest'
      ),
      api.post_check(
          post_process.MustRun,
          'clone main of https://chromium.googlesource.com/chromiumos/codesearch'
      ),
      api.step_data('fetch hash',
                    api.raw_io.stream_output_text('d3adb33f', stream='stdout')),
      api.post_process(post_process.LogContains, 'luci-scheduler.EmitTriggers',
                       'input', [
                           '"codesearch_mirror_revision": "d3adb33f"',
                           '"job": "amd64-generic-codesearch"',
                           '"job": "arm64-generic-codesearch"',
                       ]))
