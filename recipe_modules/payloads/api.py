# Copyright 2019 The Chromium Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

import os

from recipe_engine import recipe_api


class PayloadsApi(recipe_api.RecipeApi):
  """A module for payload generation steps"""

  def _chroot_relpath(self, path):
    """Returns path relative to chroot.

    Arguments:
      * path (str): Absolute path.

    Returns:
      str: Path relative to chroot.
    """
    return os.path.relpath(str(path), str(self.m.cros_sdk.chroot_path))

  @property
  def payload_path(self):
    return 'generate_payloads'

  def generate_full(self, image_path, output_filename,
      kern_filename, root_filename):
    """Generates full payload for hw testing.

    Args:
      * image_path (Path): The path to the image
          to generate payloads to. Must be subdir of chroot.
      * output_filename (str): Output filename.
      * kern_filename (str): Out KERN filename.
      * root_filename (str): Out ROOT filename.
    """
    payload_path = os.path.join('workspace', self.payload_path)
    chroot_image_relpath = self._chroot_relpath(image_path)

    cmd = [
        'src/scripts/cros_generate_update_payload',
        '--image', chroot_image_relpath,
        '--output', os.path.join(payload_path, output_filename),
        '--kern_path',
        os.path.join(payload_path, kern_filename),
        '--root_pretruncate_path',
        os.path.join(payload_path, root_filename)
    ]

    workspace = self.m.path['cleanup']
    self.m.cros_sdk.run('Generate full payload', cmd, workspace=workspace)

  def generate_delta(self, image_path, output_filename):
    """Generates delta payload for hw testing.

    Args:
      * image_path (Path): The path to the image
          to generate payloads to. Must be subdir of chroot.
      * output_filename (str): Output filename.
    """
    payload_path = os.path.join('workspace', self.payload_path)
    chroot_image_relpath = self._chroot_relpath(image_path)

    cmd = [
        'src/scripts/cros_generate_update_payload',
        '--image', chroot_image_relpath,
        '--output', os.path.join(payload_path, output_filename),
        '--src_image',
        chroot_image_relpath
    ]

    self.m.cros_sdk.run('Generate delta payload', cmd)

  def generate_stateful(self, image_path):
    """Generates stateful payload for hw testing.

    Args:
      * image_path (Path): The path to the image
          to generate payloads to. Must be subdir of chroot.
    """
    payload_path = os.path.join('workspace', self.payload_path)
    chroot_image_relpath = self._chroot_relpath(image_path)

    cmd = [
        'src/scripts/cros_generate_stateful_update_payload',
        '--image', chroot_image_relpath,
        '--output', payload_path,
    ]

    self.m.cros_sdk.run('Generate stateful payload', cmd)
