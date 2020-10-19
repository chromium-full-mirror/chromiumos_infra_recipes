# -*- coding: utf-8 -*-
# Copyright 2020 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""API featuring shared helpers for locating and naming stored artifacts.

   Much of the inspiration for this module came from:
       chromite/lib/paygen/gspaths.py

   As long as there are two versions of the the path construction any changes
   to one of these needs to be reflected in the other.
"""

from recipe_engine import recipe_api
from os import path

from PB.chromiumos.common import ImageType


class UnsupportedImageTypeException(Exception):
  """Throw this if trying to create image with unsuported ImageType."""
  pass


class ArtifactRoot():
  """The directory root of the build."""

  _URI_TEMPLATE = 'gs://%(bucket)s/%(channel)s/%(build_target_name)s/%(version)s'

  @property
  def build_target_name(self):
    "The string build target (e.g. 'coral')." ""
    return self._build_target_name

  @property
  def version(self):
    "The string version (e.g. '13373.1.0')." ""
    return self._version

  @property
  def channel(self):
    "The string channel (e.g. 'canary')." ""
    return self._channel

  @property
  def bucket(self):
    "The string bucket (e.g. 'chromeos-releases')." ""
    return self._bucket

  def __init__(self, bucket, channel, build_target_name, version):
    """A build's root location.

    Args:
      bucket (str): A root path portion (e.g. chromeos-releases).
      channel (str): A channel (e.g. canary, dev, stable, beta).
      build_target_name (str): Also known as a board (e.g. coral).
      version (str): The chromeos version (e.g. 13373.1.4).
    """
    self._bucket = bucket
    # Properties are set for these because they're duplicated in image names.
    self._build_target_name = build_target_name
    self._version = version
    self._channel = channel

  @property
  def uri(self):
    """A buildroot's uri. Often composed with image path info."""
    return self._URI_TEMPLATE % {
        'bucket': self.bucket,
        'channel': self.channel,
        'build_target_name': self.build_target_name,
        'version': self.version
    }


class Image(object):
  """Base class of an image of a particular type resident in storage."""

  # The following image types are currently supported in this module.
  _SUPPORTED_IMAGE_TYPES = [
      ImageType.Value('RECOVERY'),
      ImageType.Value('BASE')
  ]

  @property
  def uri(self):
    """An Image's full uri."""
    return path.join(self._artifact_root.uri, self.basename)

  def __init__(self, artifact_root, image_type):
    if image_type not in self._SUPPORTED_IMAGE_TYPES:
      raise UnsupportedImageTypeException()
    self._artifact_root = artifact_root
    self._image_type = image_type


class SignedImage(Image):
  """A signed image resident in storage."""

  _SIGNED_IMAGE_TEMPLATE = (
      'chromeos_%(version)s_%(build_target_name)s_%(image_type)s' +
      '_%(channel)s_%(key)s.bin')

  @property
  def basename(self):
    """This is the basename portion of the path of this image type."""
    return self._SIGNED_IMAGE_TEMPLATE % {
        'channel': self._artifact_root.channel,
        'build_target_name': self._artifact_root.build_target_name,
        'version': self._artifact_root.version,
        'key': self._key,
        'image_type': ImageType.Name(self._image_type).lower(),
    }

  def __init__(self, artifact_root, image_type, key):
    """Construct a signed image instance.

    Args:
      artifact_root (ArtifactRoot): A ArtifactRoot instance.
      image_type (common_pb2.ImageType): The image type.
      key (str): The key the image was signed with (e.g. 'mp', 'mp-v4').
    """
    super(SignedImage, self).__init__(artifact_root, image_type)
    self._key = key


class UnsignedImage(Image):

  _UNSIGNED_IMAGE_TEMPLATE = (
      'ChromeOS-%(image_type)s-%(milestone)s-%(version)s-%(build_target_name)s.tar.xz'
  )

  @property
  def basename(self):
    """This is the basename portion of the path of this image type."""
    return self._UNSIGNED_IMAGE_TEMPLATE % {
        'build_target_name': self._artifact_root.build_target_name,
        'version': self._artifact_root.version,
        'milestone': self._milestone,
        'image_type': ImageType.Name(self._image_type).lower(),
    }

  def __init__(self, artifact_root, image_type, milestone):
    """Construct an unsigned image instance.

    Args:
      artifact_root (ArtifactRoot): A ArtifactRoot instance.
      image_type (common_pb2.ImageType): The image type.
      milestone (str): The milestone of image (e.g. 'R84', 'R34').
    """
    super(UnsignedImage, self).__init__(artifact_root, image_type)
    self._milestone = milestone


class CrosStorageApi(recipe_api.RecipeApi):
  UnsupportedImageTypeException = UnsupportedImageTypeException
  ArtifactRoot = ArtifactRoot
  SignedImage = SignedImage
  UnsignedImage = UnsignedImage
