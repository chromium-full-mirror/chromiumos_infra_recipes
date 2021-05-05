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

import json
from os import path
import re

from recipe_engine import recipe_api
from PB.chromite.api.payload import Build as Build_pb2
from PB.chromite.api.payload import DLCImage as DLCImage_pb2
from PB.chromite.api.payload import SignedImage as SignedImage_pb2
from PB.chromite.api.payload import UnsignedImage as UnsignedImage_pb2
from PB.chromiumos.common import BuildTarget, ImageType

# Number of seconds to wait on gsutil ops.
GSUTIL_TIMEOUT_SECONDS = 30 * 60


class UnsupportedImageTypeException(Exception):
  """Throw this if trying to create image with unsuported ImageType."""
  pass


class ArtifactRoot():
  """The directory root of the build."""

  _URI_TEMPLATE = 'gs://%(bucket)s/%(channel)s/%(build_target_name)s/%(version)s'

  _VERSION_EXP = r'[0-9][0-9.]+[0-9]'
  _CHANNEL_EXP = r'(canary-channel|dev-channel|beta-channel|stable-channel)'

  _ARTIFACTROOT_URI_EXP = (r'gs://(?P<bucket>[^/]+)/(?P<channel>%s)/'
                           r'(?P<build_target>[^/]+)/(?P<version>%s)' %
                           (_CHANNEL_EXP, _VERSION_EXP))

  @property
  def build_target_name(self):
    """The string build target (e.g. 'coral')."""
    return self._build_target_name

  @property
  def version(self):
    """The string version (e.g. '13373.1.0')."""
    return self._version

  @property
  def channel(self):
    """The string channel, with '-channel' (e.g. 'canary-channel')."""
    return self._channel

  @property
  def bucket(self):
    """The string bucket (e.g. 'chromeos-releases')."""
    return self._bucket

  @classmethod
  def parse_uri(cls, uri):
    """Construct a ArtifactRoot from the passed uri string."""
    m = re.match(cls._ARTIFACTROOT_URI_EXP, uri)
    if not m:
      return None
    values = m.groupdict()
    return ArtifactRoot(values['bucket'], values['channel'],
                        values['build_target'], values['version'])

  def __init__(self, bucket, channel, build_target_name, version):
    """A build's artifact root location.

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
  # TODO(crbug.com/1122854): Refer via ImageType.Value, and remove aliases.
  _SUPPORTED_IMAGE_TYPES = [1, 3, 6, 12]

  _IMAGE_TYPE_TO_PATH_ATOM = {
      1: "base",
      3: "test",
      6: "recovery",
      12: "dlc",
  }

  _IMAGE_TYPE_ATOM_TO_ENUM = {
      v: k for k, v in _IMAGE_TYPE_TO_PATH_ATOM.iteritems()
  }

  # Construct regex for image types (e.g. '(base|recovery|dev|test)').
  _IMAGE_TYPES_REGEXP = ('(' + '|'.join(
      [_IMAGE_TYPE_TO_PATH_ATOM[x] for x in _SUPPORTED_IMAGE_TYPES]) + ')')

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

  _SIGNED_IMAGE_REGEXP = (r'.+chromeos_(?P<image_version>[^_]+)_'
                          r'(?P<build_target>[^/]+)_'
                          r'(?P<image_type>%s)_'
                          r'(?P<image_channel>[^_]+)_'
                          r'(?P<key>[^_]+).bin$' % Image._IMAGE_TYPES_REGEXP)

  @property
  def basename(self):
    """This is the basename portion of the path of this image type."""
    return self._SIGNED_IMAGE_TEMPLATE % {
        # We strip the '-channel' here.
        'channel': self._artifact_root.channel.replace('-channel', ''),
        'build_target_name': self._artifact_root.build_target_name,
        'version': self._artifact_root.version,
        'key': self._key,
        'image_type': self._IMAGE_TYPE_TO_PATH_ATOM[self._image_type],
    }

  def to_proto(self):
    """Convert self into a chromite api SignedImage proto."""
    return SignedImage_pb2(
        build=Build_pb2(
            build_target=BuildTarget(
                name=self._artifact_root.build_target_name,
            ),
            version=self._artifact_root.version,
            bucket=self._artifact_root.bucket,
            channel=self._artifact_root.channel,
        ),
        image_type=self._image_type,
        key=self._key,
    )

  @classmethod
  def parse_uri(cls, uri):
    """Construct a SignedImage from a provided Uri, or return None."""
    ar = ArtifactRoot.parse_uri(uri)
    if not ar:
      return None
    m = re.search(cls._SIGNED_IMAGE_REGEXP, uri)
    if not m:
      return None
    values = m.groupdict()
    return SignedImage(ar, cls._IMAGE_TYPE_ATOM_TO_ENUM[values['image_type']],
                       values['key'])

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
  """An unsigned image in storage."""

  _UNSIGNED_IMAGE_TEMPLATE = (
      'ChromeOS-%(image_type)s-%(milestone)s-%(version)s-%(build_target_name)s.tar.xz'
  )

  _UNSIGNED_IMAGE_ARCHIVE_TEMPLATE = (
      'gs://chromeos-image-archive/%(build_target_name)s-release/%(milestone)s-%(version)s'
  )

  _UNSIGNED_IMAGE_REGEXP = (r'ChromeOS-(?P<image_type>%s)-'
                            r'(?P<milestone>R[0-9]+)-'
                            r'(?P<version>[^/]+)-'
                            r'(?P<build_target>[^/]+).tar.xz$' %
                            Image._IMAGE_TYPES_REGEXP)

  @property
  def basename(self):
    """This is the basename portion of the path of this image type."""
    return self._UNSIGNED_IMAGE_TEMPLATE % {
        'build_target_name': self._artifact_root.build_target_name,
        'version': self._artifact_root.version,
        'milestone': self._milestone,
        'image_type': self._IMAGE_TYPE_TO_PATH_ATOM[self._image_type],
    }

  @property
  def archive_uri(self):
    """The chromeos-image-archive directory uri for this image."""
    return self._UNSIGNED_IMAGE_ARCHIVE_TEMPLATE % {
        'build_target_name': self._artifact_root.build_target_name,
        'version': self._artifact_root.version,
        'milestone': self._milestone,
    }

  def to_proto(self):
    """Convert self into a chromite api UnsignedImage proto."""
    return UnsignedImage_pb2(
        build=Build_pb2(
            build_target=BuildTarget(
                name=self._artifact_root.build_target_name,
            ),
            version=self._artifact_root.version,
            bucket=self._artifact_root.bucket,
            channel=self._artifact_root.channel,
        ),
        image_type=self._image_type,
        milestone=self._milestone,
    )

  @classmethod
  def parse_uri(cls, uri):
    """Construct an UnsignedImage from a provided Uri, or return None."""
    ar = ArtifactRoot.parse_uri(uri)
    if not ar:
      return None
    m = re.search(cls._UNSIGNED_IMAGE_REGEXP, uri)
    if not m:
      return None
    values = m.groupdict()
    return UnsignedImage(ar, cls._IMAGE_TYPE_ATOM_TO_ENUM[values['image_type']],
                         values['milestone'])

  def __init__(self, artifact_root, image_type, milestone):
    """Construct an unsigned image instance.

    Args:
      artifact_root (ArtifactRoot): A ArtifactRoot instance.
      image_type (common_pb2.ImageType): The image type.
      milestone (str): The milestone of image (e.g. 'R84', 'R34').
    """
    super(UnsignedImage, self).__init__(artifact_root, image_type)
    self._milestone = milestone


class DLCImage(Image):
  """A DLC Image or Downloadable Content Image in storage."""

  _DLC_IMAGE_TEMPLATE = 'dlc/%(dlc_id)s/%(dlc_package)s/%(dlc_image)s'
  _DLC_REGEXP = r'/dlc/(?P<dlc_id>[^/]+)/(?P<dlc_package>[^/]+)/dlc.img$'

  @classmethod
  def parse_uri(cls, uri):
    """Construct a DLC from a provided Uri, or return None."""
    ar = ArtifactRoot.parse_uri(uri)
    if not ar:
      return None
    m = re.search(cls._DLC_REGEXP, uri)
    if not m:
      return None
    values = m.groupdict()
    return cls(ar, values['dlc_id'], values['dlc_package'], 'dlc.img')

  @classmethod
  def compatible(cls, one, other):
    """Is one DLC image proto compatible with the other DLC image proto."""
    return (one.dlc_id == other.dlc_id and
            one.dlc_package == other.dlc_package and
            one.dlc_image == other.dlc_image)

  @property
  def basename(self):
    """Basename for DLC is different, starts at the artifact root."""
    return self._DLC_IMAGE_TEMPLATE % {
        'dlc_id': self._dlc_id,
        'dlc_package': self._dlc_package,
        'dlc_image': self._dlc_image,
    }

  def to_proto(self):
    """Convert self into a chromite api DLCImage proto."""
    return DLCImage_pb2(
        build=Build_pb2(
            build_target=BuildTarget(
                name=self._artifact_root.build_target_name,
            ),
            version=self._artifact_root.version,
            bucket=self._artifact_root.bucket,
            channel=self._artifact_root.channel,
        ),
        dlc_id=self._dlc_id,
        dlc_package=self._dlc_package,
        dlc_image=self._dlc_image,
    )

  def __init__(self, artifact_root, dlc_id, dlc_package, dlc_image):
    """Construct a DLCImage instance.

    Args:
      artifact_root (ArtifactRoot): A ArtifactRoot instance.
      dlc_id (str): The name of the DLC (e.g. 'terminal-dlc').
      dlc_package (str): The DLC package name (e.g. 'package').
      dlc_image (str): The name of the dlc image (e.g. 'dlc.img').
    """
    super(DLCImage, self).__init__(artifact_root,
                                   ImageType.Value('IMAGE_TYPE_DLC'))
    self._artifact_root = artifact_root
    self._dlc_id = dlc_id
    self._dlc_package = dlc_package
    self._dlc_image = dlc_image


class Payload(object):
  """Base class of a payload of a particular type resident in storage."""

  @property
  def uri(self):
    """A Payload's full uri."""
    return path.join(self._tgt_image._artifact_root.uri, 'payloads',
                     self.basename)

  @property
  def key(self):
    """The key to sign the image with, or None."""
    return self._key

  def __init__(self, tgt_image, unique_id):
    self._tgt_image = tgt_image
    self._unique_id = unique_id
    self._key = tgt_image._key if isinstance(tgt_image, SignedImage) else None


class FullPayload(Payload):
  """A full payload resident in storage."""

  _FULL_PAYLOAD_TEMPLATE = ('chromeos_%(version)s_%(board)s_%(channel)s_'
                            'full_%(key)s.bin-%(unique_id)s%(signed_ext)s')

  # Matches a full payload basename. Example:
  # chromeos_13506.0.0_coral_dev-channel_full_test.bin-abc123
  _FULL_PAYLOAD_REGEXP = (r'chromeos_(?P<tgt_version>[^/]+)_'
                          r'(?P<build_target>[^/]+)_'
                          r'(?P<channel>[^/]+)_full_'
                          r'(?P<key>[^/]+).bin-'
                          r'(?P<unique_id>[^/.]+)'
                          r'(?P<signed_ext>(.+)?)')

  @classmethod
  def parse_uri(cls, uri, milestone=None):
    """Construct a FullPayload from a provided uri, or return None."""
    ar = ArtifactRoot.parse_uri(uri)
    if not ar:
      return None
    m = re.search(cls._FULL_PAYLOAD_REGEXP, uri)
    if not m:
      return None
    values = m.groupdict()
    if values['signed_ext'] == '.signed':
      tgt_image = SignedImage(ar, image_type=ImageType.Value('IMAGE_TYPE_TEST'),
                              key=values['key'])
    elif values['signed_ext'] == '':
      tgt_image = UnsignedImage(ar,
                                image_type=ImageType.Value('IMAGE_TYPE_TEST'),
                                milestone=milestone)
    # Filter out .json and .log files.
    else:
      return None
    return FullPayload(tgt_image, values['unique_id'])

  def __init__(self, tgt_image, unique_id):
    """Construct a FullPayload instance.

    Args:
      tgt_image (Image): A representation of the image the payload updates to.
      unique_id (str): A random value appended to payloads at generation time.
    """
    super(FullPayload, self).__init__(tgt_image, unique_id)

  @property
  def basename(self):
    """The basename portion of the path of a FullPayload."""
    artifact_root = self._tgt_image._artifact_root
    return self._FULL_PAYLOAD_TEMPLATE % {
        'channel': artifact_root.channel,
        'board': artifact_root.build_target_name,
        'version': artifact_root.version,
        'key': self.key or 'test',
        'unique_id': self._unique_id,
        'signed_ext': '.signed' if self._key else '',
    }


class DeltaPayload(Payload):
  """A delta payload resident in storage."""

  _DELTA_PAYLOAD_TEMPLATE = (
      'chromeos_%(src_version)s-%(version)s_%(board)s_%(channel)s_'
      'delta_%(key)s.bin-%(unique_id)s%(signed_ext)s')

  # Matches a delta payload basename. Example:
  # chromeos_13502.0.0-13506.0.0_coral_dev-channel_delta_mp-v5.bin-abc123.signed
  _DELTA_PAYLOAD_REGEXP = (r'chromeos_'
                           r'(?P<src_version>[^/]+)-'
                           r'(?P<tgt_version>[^/]+)_'
                           r'(?P<build_target>[^/]+)_'
                           r'(?P<channel>[^/]+)_delta_'
                           r'(?P<key>[^/]+).bin-'
                           r'(?P<unique_id>[^/.]+)'
                           r'(?P<signed_ext>(.+)?)')

  @classmethod
  def parse_uri(cls, uri, milestone=None):
    """Construct a DeltaPayload from a provided uri, or return None."""
    tgt_ar = ArtifactRoot.parse_uri(uri)
    if not tgt_ar:
      return None
    m = re.search(cls._DELTA_PAYLOAD_REGEXP, uri)
    if not m:
      return None
    values = m.groupdict()

    src_ar = ArtifactRoot.parse_uri(uri)
    src_ar.version = values['src_version']

    if values['signed_ext'] == '.signed':
      tgt_image = SignedImage(tgt_ar,
                              image_type=ImageType.Value('IMAGE_TYPE_TEST'),
                              key=values['key'])
      src_image = SignedImage(src_ar,
                              image_type=ImageType.Value('IMAGE_TYPE_TEST'),
                              key=values['key'])
    elif values['signed_ext'] == '':
      tgt_image = UnsignedImage(tgt_ar,
                                image_type=ImageType.Value('IMAGE_TYPE_TEST'),
                                milestone=milestone)
      src_image = UnsignedImage(src_ar,
                                image_type=ImageType.Value('IMAGE_TYPE_TEST'),
                                milestone=milestone)
    # Filter out .json and .log files.
    else:
      return None
    return DeltaPayload(tgt_image, src_image, values['unique_id'])

  @property
  def basename(self):
    """The basename portion of the path of a DeltaPayload."""
    artifact_root = self._tgt_image._artifact_root
    return self._DELTA_PAYLOAD_TEMPLATE % {
        'channel': artifact_root.channel,
        'board': artifact_root.build_target_name,
        'version': artifact_root.version,
        'key': self.key or 'test',
        'unique_id': self._unique_id,
        'src_version': self._src_image._artifact_root.version,
        'signed_ext': '.signed' if self._key else '',
    }

  def __init__(self, tgt_image, src_image, unique_id):
    """Construct a DeltaPayload instance.

    Args:
      tgt_image (Image): A representation of the image the payload updates to.
      src_image (Image): A representation of the image the payload updates from.
      unique_id (str): A random value appended to payloads at generation time.
    """
    super(DeltaPayload, self).__init__(tgt_image, unique_id)
    self._src_image = src_image


class DLCPayload(Payload):
  """A DLCPayload is a payload type for DLCs."""

  # The url for a DLCPayload isn't encoded with this, so we must assume it.
  _DEFAULT_DLC_IMAGE_NAME = 'dlc.img'

  @property
  def uri(self):
    """A DLC Payload's full uri, overrides Payload's impl."""
    return path.join(self._tgt_image._artifact_root.uri, 'payloads', 'dlc',
                     self._tgt_image._dlc_id, self._tgt_image._dlc_package,
                     self.basename)

  def __init__(self, *args, **kwargs):
    """Initialize a DLCPayload."""
    super(DLCPayload, self).__init__(*args, **kwargs)


class FullDLCPayload(DLCPayload):
  """A full dlc payload resident in storage."""

  _FULL_DLC_PAYLOAD_TEMPLATE = (
      'dlc_%(dlc_id)s_%(dlc_package)s_%(tgt_version)s_'
      '%(build_target)s_%(channel)s_full.bin-%(unique_id)s.signed')

  # Matches a full dlc payload basename. Example:
  # dlc_termina-dlc_package_13505.33.0_fizz_beta-channel_fullt :.bin-gvtgcmjugztghjioi4bbf32rlvybuioo.signed
  _FULL_DLC_PAYLOAD_REGEXP = (r'dlc_'
                              r'(?P<dlc_id>[^/]+)_'
                              r'(?P<dlc_package>[^/]+)_'
                              r'(?P<tgt_version>[^/]+)_'
                              r'(?P<build_target>[^/]+)_'
                              r'(?P<channel>[^/]+)_full\.bin-'
                              r'(?P<unique_id>[^/^\.]+)\.signed$')

  @classmethod
  def parse_uri(cls, uri):
    """Construct a FullDLCPayload from a provided uri, or return None."""
    tgt_ar = ArtifactRoot.parse_uri(uri)
    if not tgt_ar:
      return None
    m = re.search(cls._FULL_DLC_PAYLOAD_REGEXP, uri)
    if not m:
      return None
    values = m.groupdict()

    tgt_dlc_image = DLCImage(tgt_ar, values['dlc_id'], values['dlc_package'],
                             super(FullDLCPayload, cls)._DEFAULT_DLC_IMAGE_NAME)
    return FullDLCPayload(tgt_dlc_image, values['unique_id'])

  @property
  def basename(self):
    """The basename portion of the path of a FullDLCPayload."""
    artifact_root = self._tgt_image._artifact_root
    return self._FULL_DLC_PAYLOAD_TEMPLATE % {
        'dlc_id': self._tgt_image._dlc_id,
        'dlc_package': self._tgt_image._dlc_package,
        'tgt_version': artifact_root.version,
        'build_target': artifact_root.build_target_name,
        'channel': artifact_root.channel,
        'unique_id': self._unique_id,
    }

  def __init__(self, tgt_image, unique_id):
    """Construct a FullDLCPayload instance.

    Args:
      tgt_image (Image): A representation of the image the payload updates to.
      unique_id (str): A random value appended to payloads at generation time.
    """
    super(FullDLCPayload, self).__init__(tgt_image, unique_id)


class DeltaDLCPayload(DLCPayload):
  """A delta dlc payload resident in storage."""

  _DELTA_DLC_PAYLOAD_TEMPLATE = (
      'dlc_%(dlc_id)s_%(dlc_package)s_%(src_version)s-%(tgt_version)s_'
      '%(build_target)s_%(channel)s_delta.bin-%(unique_id)s.signed')

  # Matches a delta dlc payload basename. Example:
  # dlc_termina-dlc_package_13505.27.0-13505.33.0_fizz_beta-channel_delta.bin-gvtgcmjugztghjioi4bbf32rlvybuioo.signed
  _DELTA_DLC_PAYLOAD_REGEXP = (r'dlc_'
                               r'(?P<dlc_id>[^/]+)_'
                               r'(?P<dlc_package>[^/]+)_'
                               r'(?P<src_version>[^/]+)-'
                               r'(?P<tgt_version>[^/]+)_'
                               r'(?P<build_target>[^/]+)_'
                               r'(?P<channel>[^/]+)_delta\.bin-'
                               r'(?P<unique_id>[^/^\.]+)\.signed$')

  @classmethod
  def parse_uri(cls, uri):
    """Construct a DeltaDLCPayload from a provided uri, or return None."""
    tgt_ar = ArtifactRoot.parse_uri(uri)
    if not tgt_ar:
      return None
    m = re.search(cls._DELTA_DLC_PAYLOAD_REGEXP, uri)
    if not m:
      return None
    values = m.groupdict()

    src_ar = ArtifactRoot.parse_uri(uri)
    src_ar.version = values['src_version']

    tgt_dlc_image = DLCImage(
        tgt_ar, values['dlc_id'], values['dlc_package'],
        super(DeltaDLCPayload, cls)._DEFAULT_DLC_IMAGE_NAME)
    src_dlc_image = DLCImage(
        src_ar, values['dlc_id'], values['dlc_package'],
        super(DeltaDLCPayload, cls)._DEFAULT_DLC_IMAGE_NAME)
    return DeltaDLCPayload(tgt_dlc_image, src_dlc_image, values['unique_id'])

  @property
  def basename(self):
    """The basename portion of the path of a DeltaDLCPayload."""
    artifact_root = self._tgt_image._artifact_root
    return self._DELTA_DLC_PAYLOAD_TEMPLATE % {
        'dlc_id': self._tgt_image._dlc_id,
        'dlc_package': self._tgt_image._dlc_package,
        'src_version': self._src_image._artifact_root.version,
        'tgt_version': artifact_root.version,
        'build_target': artifact_root.build_target_name,
        'channel': artifact_root.channel,
        'unique_id': self._unique_id,
    }

  def __init__(self, tgt_image, src_image, unique_id):
    """Construct a DeltaDLCPayload instance.

    Args:
      tgt_image (Image): A representation of the image the payload updates to.
      src_image (Image): A representation of the image the payload updates from.
      unique_id (str): A random value appended to payloads at generation time.
    """
    super(DeltaDLCPayload, self).__init__(tgt_image, unique_id)
    self._src_image = src_image


class CrosStorageApi(recipe_api.RecipeApi):
  """Apis for dealing with stored images, payloads, and artifacts."""

  UnsupportedImageTypeException = UnsupportedImageTypeException

  ArtifactRoot = ArtifactRoot
  SignedImage = SignedImage
  UnsignedImage = UnsignedImage
  DLCImage = DLCImage
  FullPayload = FullPayload
  DeltaPayload = DeltaPayload
  FullDLCPayload = FullDLCPayload
  DeltaDLCPayload = DeltaDLCPayload

  image_types = [
      UnsignedImage.parse_uri,
      SignedImage.parse_uri,
      DLCImage.parse_uri,
  ]

  payload_types = [
      FullPayload.parse_uri,
      DeltaPayload.parse_uri,
      FullDLCPayload.parse_uri,
      DeltaDLCPayload.parse_uri,
  ]

  # This is the list of available URL parsers, used for discovery.
  all_artifact_types = image_types + payload_types

  def discover_gs_artifacts(self, prefix_uri, parse_types=all_artifact_types):
    """Discover and return all the GS artifacts found in a given ArtifactRoot.

    We assume that each uri will match at most a single ParserOption and we
    greedily take the first one. GS exceptions are represented as an empty
    return list.

    Args:
      prefix_uri (str): The gs path prefix recursively crawled.
      parse_types list(parse_uri()): A list of uri parser fn()s to consider.

    Returns:
      list[artifact_type]: list of artifacts found in the prefix.
    """
    with self.m.step.nest('discover gs artifacts') as presentation:
      recursive_uri = path.join(prefix_uri, '**')
      gsutil_ls_stdout = self.m.raw_io.output_text(name='ls results',
                                                   add_output_log=True)
      artifacts = []
      try:
        listing = self.m.gsutil.list(recursive_uri,
                                     timeout=GSUTIL_TIMEOUT_SECONDS,
                                     stdout=gsutil_ls_stdout)
      except self.m.step.StepFailure:
        return []
      for uri in listing.stdout.split():
        for po in parse_types:
          art = po(uri)
          if art:
            artifacts.append(art)
            break

      # Logs the results for inspection & return.
      presentation.logs['artifacts found'] = '\n'.join(
          [i.uri for i in artifacts])
      return artifacts
