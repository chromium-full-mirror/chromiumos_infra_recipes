# -*- coding: utf-8 -*-
# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe module to perform a build on an old checkout state."""

from typing import List

# pylint: disable=import-error
from PB.chromiumos.builder_config import BuilderConfig
from PB.chromiumos.common import PackageInfo
from PB.go.chromium.org.luci.buildbucket.proto.common import GitilesCommit
from PB.recipe_modules.chromeos.incremental.incremental import IncrementalProperties
from recipe_engine.recipe_api import RecipeApi

PYTHON_VERSION_COMPATIBILITY = 'PY3'
REPO_SYNC_JOBS = 64


class IncrementalApi(RecipeApi):
  """Module for performing builds on old checkout state."""

  def __init__(self, _properties, *args, **kwargs):
    super().__init__(*args, **kwargs)

  def DoOldBuild(self, api: RecipeApi, config: BuilderConfig,
                 properties: IncrementalProperties) -> List[PackageInfo]:
    """Rewind the checkout, install packages, and then forward the checkout.

        Args:
            api: The recipe API.
            config: The BuilderConfig for this incremental builder.
            properties: Input properties for this build.

        Returns:
            A list of relevant packages built.
        """
    is_public = config.general.manifest == BuilderConfig.General.PUBLIC

    snapshot_branch_name = 'origin/snapshot'
    build_time_delta = properties.build_time_delta
    manifest_tempdir = api.path.mkdtemp()
    manifest_url = (
        'https://chromium.googlesource.com/chromiumos/manifest'
        if is_public else
        'https://chrome-internal.googlesource.com/chromeos/manifest-internal')
    repo_path = str(api.repo.repo_path)

    # Checkout and attempt to build the old snapshot.
    api.git.clone(manifest_url, target_path=manifest_tempdir)

    # Get old snapshot hash.
    delta_hash_result = api.step(
        f'Get {build_time_delta} manifest snapshot',
        [
            'git',
            '-C',
            manifest_tempdir,
            'rev-list',
            '-1',
            '--before',
            build_time_delta,
            snapshot_branch_name,
        ],
        stdout=api.raw_io.output_text(),
    )
    delta_hash = delta_hash_result.stdout.strip()

    # Rewind the source to old snapshot.
    api.step(
        f'Revert manifest to {build_time_delta} snapshot',
        ['git', '-C', manifest_tempdir, 'checkout', delta_hash],
    )
    with api.repo.m.depot_tools.on_path():
      api.step(
          f'Apply {build_time_delta} manifest snapshot',
          [
              repo_path,
              'init',
              '--standalone-manifest',
              '--depth',
              1,
              f'file://{manifest_tempdir}/snapshot.xml',
          ],
      )
    api.repo.sync(
        jobs=REPO_SYNC_JOBS,
        force_sync=True,
        detach=True,
        retry_fetches=3,
        no_tags=True,
        current_branch=True,
        force_remove_dirty=True,
    )
    api.build_menu.setup_chroot(
        no_chroot_timeout=False,
        bootstrap=False,
        replace=False,
        update=False,
        uprev_packages=False,
        setup_toolchains_if_no_update=False,
    )

    api.cros_sdk.update_chroot(
        toolchain_targets=[api.build_menu.build_target],
        build_source=config.build.sdk_update.compile_source,
    )
    # Use the prebuilts metadata for the old manifest.
    old_commit = GitilesCommit(
        host=api.src_state.gitiles_commit.host,
        project=api.src_state.gitiles_commit.project,
        id=delta_hash,
    )
    env_info = api.build_menu.setup_sysroot_and_determine_relevance(
        snapshot_commit=old_commit if delta_hash else None)
    packages = env_info.packages
    api.build_menu.bootstrap_sysroot(config)
    api.build_menu.install_packages(config, packages)

    # Attempt to checkout the current snapshot.
    if properties.use_llfg:
      with api.repo.m.depot_tools.on_path():
        api.step(
            'Apply LLFG manifest snapshot',
            [repo_path, 'init', '--u', manifest_url, '-b', 'stable'],
        )
    else:
      with api.repo.m.depot_tools.on_path():
        api.step(
            'Apply latest manifest snapshot',
            [repo_path, 'init', '--u', manifest_url, '-b', 'snapshot'],
        )
    api.repo.sync(
        jobs=REPO_SYNC_JOBS,
        force_sync=True,
        detach=True,
        retry_fetches=3,
        force_remove_dirty=True,
    )
    api.cros_sdk(
        'regenerate configs',
        [
            'setup_board',
            '--regen-configs',
            '--board',
            api.build_menu.build_target.name,
        ],
    )

    return packages
