# -*- coding: utf-8 -*-
# Copyright 2018 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API for working with the protobuf-based Build API."""

from recipe_engine import recipe_api

INPUT_FILENAME = 'input_proto.json'
OUTPUT_FILENAME = 'output_proto.json'


class BuildApiApi(recipe_api.RecipeApi):
  """A module for CrOS Build API steps."""

  def _call(self, service_method, input_msg, output_msg_class):
    """Call a Build API method.

    Args:
      service_method (str): The service/method path (ex.
          chromium.api.Service/Method).
      input_msg (google.protobuf.message.Message): Input message.
      output_msg_class (type[Out]): Output message class.

    Returns:
      Out: Output message.

    """
    with self.m.tempfile.temp_dir('build_api_messages') as workspace_path:
      input_path = workspace_path.join(INPUT_FILENAME)
      output_path = workspace_path.join(OUTPUT_FILENAME)
      chroot_input_path = self.m.cros_sdk.workspace_path_to_chroot(
          workspace_path,
          input_path)
      chroot_output_path = self.m.cros_sdk.workspace_path_to_chroot(
          workspace_path,
          output_path)

      # Write the input proto JSON to a temp file (which is how it's passed to
      # the build API).
      self.m.file.write_raw('write input file', input_path,
                            input_msg.SerializeToString())

      # Path to bin hardcoded for now as it's not in PATH.
      bin_path = '/mnt/host/source/chromite/api/build_api'
      cmd = [bin_path, '--input-json', chroot_input_path, '--output-json',
             chroot_output_path, service_method]
      self.m.cros_sdk.run('build_api %s' % service_method, cmd,
                          workspace=workspace_path)

      output_data = self.m.file.read_text('read output file', output_path)
      return output_msg_class.FromString(output_data)
