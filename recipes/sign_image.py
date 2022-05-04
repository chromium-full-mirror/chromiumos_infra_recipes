# -*- coding: utf-8 -*-
# Copyright 2019 The Chromium OS Authors. All rights reserved.
# Use of this source code is governed by a BSD-style license that can be
# found in the LICENSE file.

"""Recipe for signing ChromeOS images."""

# This recipe is temporarily being used to convert buildbucket jobs to sign a
# gsc_firmware image into signing instructions uploaded to gs. This will allow
# the GSC team to upload signing instructions without needing write access to
# gs://chromeos-releases.

# When image signing starts being scheduled via buildbucket jobs instead of
# uploaded instruction files, the recipe will need to be modified to actually
# sign the image, instead of uploading instructions files.

import os
import re
import string

from PB.chromiumos import sign_image as sign_image_os
from PB.chromiumos import common as common_os
from PB.chromiumos.common import ImageType
from PB.chromiumos.common import BuildTarget
from PB.chromiumos.sign_image import GscInstructions
from PB.recipes.chromeos.sign_image import SignImageProperties
from PB.recipe_engine import result as result_pb2
from PB.go.chromium.org.luci.buildbucket.proto import common as common_pb2
from recipe_engine import post_process

DEPS = [
    'depot_tools/gsutil',
    'recipe_engine/buildbucket',
    'recipe_engine/file',
    'recipe_engine/path',
    'recipe_engine/properties',
    'recipe_engine/random',
    'recipe_engine/step',
    'cros_infra_config',
    'easy',
]

PYTHON_VERSION_COMPATIBILITY = 'PY2+3'

PROPERTIES = SignImageProperties


class _BucketBase(object):

  def __init__(self, bucket, base):
    self.bucket = bucket.strip('/')
    self.base = base.lstrip('/')

  def gs_path(self, *args):
    """Returns the full gs:// path for |name|."""
    path = os.path.join(self.bucket, self.base, *[x.strip('/') for x in args])
    return 'gs://' + path

  def rel_path(self, path=None):
    """Returns the relative path for |name|.

    Args:
      path (str): gs://url to remove the prefix from.

    Returns:
      str: path relative to the bucket prefix.
    """
    assert path.startswith(self.gs_path())
    return path[len(self.gs_path()):]

  def path_in_bucket(self, path):
    """Is this gs:// path in this bucket/base.

    Args:
      path (str): gs:// url to check.

    Returns:
      bool: whether the url is in this bucket/base.
    """
    return path.startswith(self.gs_path())


_release_signer_buckets = {
    sign_image_os.SIGNER_PRODUCTION: _BucketBase('chromeos-releases/', '/'),
    sign_image_os.SIGNER_STAGING: _BucketBase('chromeos-releases-test/', '/'),
    sign_image_os.SIGNER_DEV: _BucketBase('chromeos-releases-test/', '/'),
}

_non_release_signer_buckets = {
    sign_image_os.SIGNER_PRODUCTION:
        _BucketBase('chromeos-image-archive/', '/'),
    sign_image_os.SIGNER_STAGING:
        _BucketBase('staging-chromeos-image-archive/', '/'),
    sign_image_os.SIGNER_DEV:
        _BucketBase('staging-chromeos-image-archive/', '/'),
}

# Map gsc_instructions.target to the text value for instructions.
# Capitals with underscores becomes CamelCase, with a couple of exceptions.
_target_type_to_name = {
    v: (k.title().replace('_',
                          '').replace('Prepvt',
                                      'PrePVT').replace('Unspecified',
                                                        'Unchanged'))
    for k, v in GscInstructions.Target.items()
}

# Map channel numbers to names.
_channel_to_name = {
    v: k.lower().replace('channel_', '') for k, v in common_os.Channel.items()
}


def RunSteps(api, properties):
  """Run steps."""
  api.easy.log_parent_step()

  local_dir = api.path['cleanup']
  non_release_signer_bucket = False

  with api.step.nest('determine is_staging') as presentation:
    # Configure knowledge of whether this is running in staging.
    api.cros_infra_config.determine_if_staging()
    presentation.step_text = "Running build with is_staging set to {}".format(
        api.cros_infra_config.is_staging)

  with api.step.nest('validate request') as presentation:
    image_type = properties.image_type
    # We operate here on image type names sans IMAGE_TYPE_ prefix.
    image_type_name = re.sub('image_type_', '',
                             ImageType.Name(image_type).lower())
    # TODO(lamontjones): Extend this to checking the config for the list of
    # permitted image_types.  Today, only gsc_firmware is permitted.
    if image_type != common_os.IMAGE_TYPE_GSC_FIRMWARE:
      return result_pb2.RawResult(
          status=common_pb2.FAILURE, summary_markdown='illegal image type %s' %
          (ImageType.Name(image_type)))

    if properties.signer_type == sign_image_os.SIGNER_UNSPECIFIED:
      signer_type = sign_image_os.SIGNER_PRODUCTION
    else:
      signer_type = properties.signer_type
    gs = _release_signer_buckets[signer_type]
    prod = _release_signer_buckets[sign_image_os.SIGNER_PRODUCTION]
    non_release_gs = _non_release_signer_buckets[signer_type]

    # The archive must point to a valid location.  In addition to inside their
    # own bucket, any instance is allowed to use the production bucket for
    # images to sign.  If needed, copy the archive into the non-prod bucket.
    archive = properties.archive
    if not gs.path_in_bucket(archive):
      if prod.path_in_bucket(archive):
        # We know that the archive is not in OUR bucket, but it is in the prod
        # bucket.  Copy it into place and adjust the archive path.
        new_archive = gs.gs_path(prod.rel_path(archive))
        api.gsutil(['cp', archive, new_archive])
        archive = new_archive
      else:
        if properties.allow_non_release_signer_bucket and non_release_gs.path_in_bucket(
            archive):
          non_release_signer_bucket = True
        else:
          return result_pb2.RawResult(
              status=common_pb2.FAILURE,
              summary_markdown='illegal archive location: %s' % archive)

    # GSC specific handling.
    gsc = properties.gsc_instructions
    if gsc.target == GscInstructions.NODE_LOCKED and not gsc.device_id:
      return result_pb2.RawResult(status=common_pb2.FAILURE,
                                  summary_markdown='must set device_id')

    presentation.step_text = 'all properties good'

  # Copy artifact to release bucket if archive is in non release bucket.
  if non_release_signer_bucket:
    with api.step.nest('copy artifacts to release bucket') as presentation:
      # Update gs bucket for new archive.
      new_archive = archive.replace(non_release_gs.bucket, gs.bucket)
      # Add new directory and copy the artifact.
      base = os.path.basename(new_archive)
      new_archive = os.path.join(os.path.dirname(new_archive), base, base)
      api.gsutil.copy(non_release_gs.bucket, non_release_gs.rel_path(archive),
                      gs.bucket, gs.rel_path(new_archive))
      # Update archive.
      archive = new_archive

  with api.step.nest('create GSC instructions'):
    target = _target_type_to_name[gsc.target]
    channel = _channel_to_name[properties.channel]

    archive_base = os.path.basename(archive)

    # These are required to be in the instructions file, but are not actually
    # used in GSC signing.  They would need to be passed in via properties if
    # we decide that we need them.
    milestone = 'RNone'
    version = 'Unknown'
    versionrev = '%s-%s' % (milestone, version)
    if properties.build_target.name:
      build_target = properties.build_target.name
    else:
      build_target = 'Unknown'

    insns = [
        '[general]',
        'archive = %s' % archive_base,
        'board = %s' % build_target,
        'type = %s' % image_type_name,
        'milestone = %s' % milestone,
        'version = %s' % version,
        'versionrev = %s' % versionrev,
        '[insns]',
        'channel = %s' % channel,
        'keyset = %s' % properties.keyset,
        'target = %s' % target,
    ]
    if target == 'NodeLocked':
      insns.append(
          'output_names = @CHIP@_@VERSION@_@TARGET@-@DEVICE_ID@_@KEYSET@')
      insns.append('device_id = %s' % gsc.device_id)
    else:
      insns.append('output_names = @CHIP@_@VERSION@_@TARGET@_@KEYSET@')

  with api.step.nest('upload gsc instructions') as presentation:
    content = str('\n'.join(insns) + '\n')
    # crbug.com/1025023: Don't clobber other pending instructions files.
    random_suffix = ''.join(
        api.random.choice(string.ascii_letters) for n in range(8))
    insn_basename = 'ChromeOS-%s-%s-%s-%s.instructions' % (
        image_type_name, versionrev, properties.keyset, random_suffix)
    local_insn = local_dir.join(insn_basename)
    insn_path = os.path.join(os.path.dirname(archive), insn_basename)
    rel_insn_path = gs.rel_path(insn_path)

    api.file.write_raw(name='instructions file', dest=local_insn, data=content)

    api.gsutil(['cp', local_insn, insn_path])
    presentation.step_text = 'instructions uploaded'
    api.easy.set_properties_step(instructions_file=insn_path)

  with api.step.nest('trigger gsc signing') as presentation:
    if not api.cros_infra_config.is_staging:
      # TODO(lamontjones): Put some info there instead of /dev/null.
      trigger_data = r''
      trigger_base = '50,' + rel_insn_path.replace('/', ',')
      trigger_path = gs.gs_path('tobesigned', trigger_base)

      local_trigger = local_dir.join(trigger_base)
      api.file.write_raw(name='trigger file', dest=local_trigger,
                         data=trigger_data)
      api.gsutil(['cp', local_trigger, trigger_path])
      presentation.step_text = 'trigger uploaded'
    else:
      presentation.step_text = "skipped in staging"


def GenTests(api):

  def props(**kwargs):
    return api.properties(SignImageProperties(**kwargs))

  def check_build_output(check, steps, output_prop, value):
    check(post_process.GetBuildProperties(steps).get(output_prop) == value)

  yield api.test('basic')

  yield api.test(
      'gsc',
      props(
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          keyset='cr50-accessory-mp', channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2')))

  yield api.test(
      'gsc-bad-path',
      props(
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          keyset='cr50-accessory-mp', channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases-test/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2')))

  yield api.test(
      'gsc-staging-with-prod-path',
      props(
          signer_type=sign_image_os.SIGNER_STAGING,
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          build_target=BuildTarget(name='board'), keyset='cr50-accessory-mp',
          channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2')))

  yield api.test(
      'gsc-NodeLocked-no-device-id',
      props(
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          keyset='cr50-accessory-mp', channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'),
          gsc_instructions=GscInstructions(target=GscInstructions.NODE_LOCKED)))

  yield api.test(
      'gsc-NodeLocked',
      props(
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-releases/canary-channel/eve/12499.10.0/'
                   'ChromeOS-cr50_firmware-R78-12499.10.0-eve.tar.bz2'),
          keyset='cr50-accessory-mp',
          gsc_instructions=GscInstructions(target=GscInstructions.NODE_LOCKED,
                                           device_id='12345678-11223344')))

  yield api.test(
      'gsc-non-release-bucket-prod',
      props(
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          keyset='ti50-accessory-premp', channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-image-archive/firmware-ti50-postsubmit/'
                   'R97-14299.0.0-55770-8832698563268919201/ti50.tar.bz2'),
          allow_non_release_signer_bucket=True),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'copy artifacts to release bucket'),
      api.post_check(post_process.MustRun, 'trigger gsc signing.trigger file'),
      api.post_check(lambda check, steps: check_build_output(
          check, steps, 'instructions_file',
          'gs://chromeos-releases/firmware-ti50-postsubmit/R97-14299.0.0-55770-8832698563268919201/ti50.tar.bz2/ChromeOS-gsc_firmware-RNone-Unknown-ti50-accessory-premp-YwaVWEIe.instructions'
      )))

  yield api.test(
      'gsc-non-release-bucket-prod-efi',
      props(
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          keyset='ti50-accessory-premp', channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-image-archive/firmware-ti50-postsubmit/'
                   'R97-14299.0.0-55770-8832698563268919201/ti50.efi.tar.bz2'),
          allow_non_release_signer_bucket=True),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'copy artifacts to release bucket'),
      api.post_check(lambda check, steps: check_build_output(
          check, steps, 'instructions_file',
          'gs://chromeos-releases/firmware-ti50-postsubmit/R97-14299.0.0-55770-8832698563268919201/ti50.efi.tar.bz2/ChromeOS-gsc_firmware-RNone-Unknown-ti50-accessory-premp-YwaVWEIe.instructions'
      )))

  yield api.test(
      'gsc-non-release-bucket-prod-not-allowed',
      props(
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          keyset='ti50-accessory-premp', channel=common_os.CHANNEL_CANARY,
          archive=('gs://chromeos-image-archive/firmware-ti50-postsubmit/'
                   'R97-14299.0.0-55770-8832698563268919201/ti50.tar.bz2'),
          allow_non_release_signer_bucket=False),
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.DoesNotRun,
                     'copy artifacts to release bucket'))

  yield api.test(
      'gsc-non-release-bucket-staging',
      api.buildbucket.generic_build(builder="staging-sign-image"),
      props(
          signer_type=sign_image_os.SIGNER_STAGING,
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          keyset='ti50-accessory-premp', channel=common_os.CHANNEL_CANARY,
          archive=(
              'gs://staging-chromeos-image-archive/firmware-ti50-postsubmit/'
              'R97-14299.0.0-55770-8832698563268919201/ti50.tar.bz2'),
          allow_non_release_signer_bucket=True),
      api.post_check(post_process.StatusSuccess),
      api.post_check(post_process.MustRun, 'copy artifacts to release bucket'),
      api.post_check(post_process.DoesNotRun,
                     'trigger gsc signing.trigger file'))

  yield api.test(
      'gsc-non-release-bucket-staging-not-allowed',
      props(
          signer_type=sign_image_os.SIGNER_STAGING,
          image_type=common_os.IMAGE_TYPE_GSC_FIRMWARE,
          keyset='ti50-accessory-premp', channel=common_os.CHANNEL_CANARY,
          archive=(
              'gs://staging-chromeos-image-archive/firmware-ti50-postsubmit/'
              'R97-14299.0.0-55770-8832698563268919201/ti50.tar.bz2'),
          allow_non_release_signer_bucket=False),
      api.post_check(post_process.StatusAnyFailure),
      api.post_check(post_process.DoesNotRun,
                     'copy artifacts to release bucket'))
