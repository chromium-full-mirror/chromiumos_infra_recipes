# -*- coding: utf-8 -*-
# Copyright 2021 The ChromiumOS Authors
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""An API for providing release related utility functions."""

from recipe_engine import recipe_api

from PB.chromiumos.common import Channel, ImageType

PYTHON_VERSION_COMPATIBILITY = 'PY3'


class CrosReleaseUtilApi(recipe_api.RecipeApi):

  @staticmethod
  def match_channels(channel1, channel2):
    """Determine if two channels are equal, even if represented differently.

    Args:
      channel1 (str|Channel): A representation of a channel, either as a Channel
        enum (e.g. Channel.CHANNEL_BETA), a short string (e.g. "beta"), or a
        long string (e.g. "beta-channel").
      channel2 (str|Channel): As above.

    Returns:
      bool: Whether the two args describe the same channel.
    """
    channel_enums = []
    for channel in (channel1, channel2):
      if channel in Channel.values():
        channel_enums.append(channel)
      elif channel.endswith('-channel'):
        channel_enums.append(
            CrosReleaseUtilApi.channel_long_string_to_enum(channel))
      else:
        channel_enums.append(
            CrosReleaseUtilApi.channel_short_string_to_enum(channel))
    return channel_enums[0] == channel_enums[1]

  @staticmethod
  def channel_strip_prefix(channel):
    """Takes a common_pb2.Channel and returns an unprefixed str (e.g. beta)."""
    return Channel.Name(channel).replace('CHANNEL_', '').lower()

  @staticmethod
  def channel_to_short_string(channel):
    """Takes a common_pb2.Channel and returns a unsuffixed str (e.g. dev)."""
    return CrosReleaseUtilApi.channel_strip_prefix(channel)

  @staticmethod
  def channel_to_long_string(channel):
    """Takes a common_pb2.Channel and returns a suffixed str (e.g. dev-channel)."""
    return CrosReleaseUtilApi.channel_to_short_string(channel) + '-channel'

  @staticmethod
  def channel_long_string_to_enum(str_channel):
    """Convert long channel name strings (e.g. 'beta-channel') to enum values."""
    return Channel.Value('CHANNEL_' + str_channel.split('-')[0].upper())

  @staticmethod
  def channel_short_string_to_enum(str_channel):
    """Convert short channel name strings (e.g. 'beta') to enum values."""
    return Channel.Value('CHANNEL_' + str_channel.upper())

  def release_builder_name(self, build_target, branch=None, staging=False):
    """Determine the Rubik child builder name for the given build_target.

      Args:
        build_target (string): name of the build target, e.g. zork or kevin-kernelnext
        branch (string): optional, branch we're on.
        staging (string): optional, whether or not we're in staging.

      Return:
        The Rubik child builder, e.g. zork-release-main.
      """
    staging_prefix = 'staging-' if (staging or
                                    self.m.cros_infra_config.is_staging) else ''
    branch_suffix = branch or self.m.cros_source.manifest_branch
    if branch_suffix.startswith('release-'):
      branch_suffix = branch_suffix[len('release-'):]
    if not branch_suffix or self.m.cros_source.is_tot:
      branch_suffix = 'main'
    target_release_builder_name = '{}{}-release-{}'.format(
        staging_prefix, build_target, branch_suffix)
    return target_release_builder_name

  def image_type_to_str(self, image_type: ImageType) -> str:
    """Extracts the image type as a lowercase string.

    E.g. IMAGE_TYPE_RECOVERY -> recovery."""
    return ImageType.Name(image_type)[len('IMAGE_TYPE_'):].lower()
