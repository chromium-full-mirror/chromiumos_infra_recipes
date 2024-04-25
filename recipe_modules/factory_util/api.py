# Copyright 2023 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""A module for util functions associated with factory builds."""

from recipe_engine import recipe_api
from recipe_engine.config_types import Path

from PB.chromiumos.builder_config import BuilderConfig


class FactoryUtilApi(recipe_api.RecipeApi):

  def __init__(self, **kwargs):
    super().__init__(**kwargs)

  def upload_factory(self, config: BuilderConfig, artifact_dir: str) -> None:
    """Compress and upload factory artifacts.

    Used for older factory branches which predate ArtifactsService.

    Args:
      config - Which contains builder info used to construct GS path.
      artifact_dir - Local dir containing build artifacts.

    """
    with self.m.step.nest('uploading factory artifacts for older branch'):
      version_str = self.m.cros_version.version.legacy_version
      images_path = self.m.cros_source.workspace_path.joinpath(
          f'src/build/images/{self.m.build_menu.build_target.name}/')
      chroot_path = self.m.path.cache_dir.joinpath('cros_chroot').joinpath(
          'chroot')
      bundle_path = chroot_path.joinpath(
          f'build/{self.m.build_menu.build_target.name}/usr/local/factory/',
          'bundle')

      self.zip_factory_image(artifact_dir, images_path, bundle_path,
                             version_str)
      self.compress_test_image(artifact_dir, images_path, version_str)
      self.upload_factory_artifacts(config, artifact_dir)

  def zip_factory_image(self, artifact_dir: str, images_path: Path,
                        bundle_path: Path, version_str: str) -> None:
    """Zip up artifacts for factory.zip"""
    factory_zip_path = self.m.path.join(artifact_dir, 'factory_image.zip')
    version_str_factory = f'{version_str}-factory_shim'

    zip_cmd = [
        'zip',
        '-r',
        factory_zip_path,
        version_str_factory,
        '--include',
        version_str_factory + '/*factory_install*.bin',
        '--include',
        version_str_factory + '/*partition*',
        '--include',
        version_str_factory + '/netboot/*',
    ]

    with self.m.context(cwd=images_path):
      self.m.step(cmd=zip_cmd, name='zip factory')

    zip_ln_cmd = [
        'zip',
        '-r',
        factory_zip_path,
        '-y',
        '.',
    ]

    with self.m.context(cwd=bundle_path):
      self.m.step(cmd=zip_ln_cmd, name='zip factory symlinks')

  def compress_test_image(self, artifact_dir: str, images_path: Path,
                          version_str: str):
    """Compress artifacts for chromiumos_test_image.tar.xz"""
    images_path = images_path / version_str
    test_tar_path = self.m.path.join(artifact_dir,
                                     'chromiumos_test_image.tar.xz')

    test_bin_path = 'chromiumos_test_image.bin'

    tar_cmd = [
        'tar',
        # xz compression.
        '-cJf',
        test_tar_path,
        test_bin_path,
    ]

    with self.m.context(cwd=images_path):
      self.m.step(cmd=tar_cmd, name='tar test image')


  def upload_factory_artifacts(self, config: BuilderConfig,
                               artifact_dir: str) -> None:
    """Upload factory.zip and chromiumos_test_image.tar.xz"""
    gs_bucket = config.artifacts.artifacts_gs_bucket
    gs_path = (
        'gs://' + gs_bucket + '/' + self.m.cros_artifacts.artifacts_gs_path(
            config.id.name, self.m.build_menu.build_target, config.id.type,
            template=self.m.cros_artifacts.gs_upload_path))

    factory_zip_path = self.m.path.join(artifact_dir, 'factory_image.zip')
    factory_cp_cmd = [
        'cp',
        factory_zip_path,
        gs_path,
    ]
    self.m.gsutil(factory_cp_cmd, multithreaded=True, timeout=15 * 60)

    test_tar_path = self.m.path.join(artifact_dir,
                                     'chromiumos_test_image.tar.xz')
    test_cp_cmd = [
        'cp',
        test_tar_path,
        gs_path,
    ]
    self.m.gsutil(test_cp_cmd, multithreaded=True, timeout=15 * 60)
