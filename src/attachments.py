"""Shared batch lookup for registered Mod/game release files."""
from typing import Iterable, Literal
from sqlmodel import Session, select, col
from models import ModRelease, GameRelease
from tables import ForumAttachment, ATTACHMENT_DETAILS


def populate_attachment_metadata(
    session: Session,
    groups: Iterable[tuple[int, list[ModRelease] | list[GameRelease], bool]],
    action: Literal['moddownload', 'gamedownload'],
) -> None:
    groups = list(groups)
    aids = sorted({r.attachment_id for _, releases, _ in groups for r in releases})
    attachments = {}
    for start in range(0, len(aids), 500):
        statement = select(ForumAttachment).where(col(ForumAttachment.aid).in_(aids[start:start + 500]))
        for attachment in session.exec(statement).all():
            attachments[attachment.aid] = attachment
    eligible = {r.attachment_id for tid, releases, _ in groups for r in releases
                if r.attachment_id in attachments and attachments[r.attachment_id].tid == tid}
    details = {}
    for shard, table in ATTACHMENT_DETAILS.items():
        shard_aids = sorted(aid for aid in eligible if attachments[aid].tableid == shard)
        for start in range(0, len(shard_aids), 500):
            statement = select(table).where(table.c.aid.in_(shard_aids[start:start + 500]))
            for detail in session.execute(statement).mappings():
                details[detail['aid']] = detail
    for tid, releases, allowed in groups:
        for release in releases:
            attachment = attachments.get(release.attachment_id)
            release.download_count = (attachment.downloads
                if attachment is not None and attachment.tid == tid and attachment.downloads >= 0 else None)
            release.file_name = release.file_size = release.download_url = release.uploaded_at = None
            detail = details.get(release.attachment_id)
            if (attachment is None or attachment.tid != tid or detail is None
                    or detail['tid'] != tid or detail['isimage'] != 0
                    or not detail['filename'] or detail['filesize'] is None or detail['filesize'] < 0):
                continue
            release.file_name = detail['filename']
            release.file_size = detail['filesize']
            uploaded_at = detail['dateline']
            release.uploaded_at = uploaded_at if isinstance(uploaded_at, int) and uploaded_at > 0 else None
            if allowed:
                release.download_url = ('https://www.fossic.org/forum.php?mod=misc&action='
                                        + action + '&aid=' + str(release.attachment_id))
