from typing import List, Optional

from sqlalchemy import func, select
from sqlalchemy.orm import aliased
from sqlalchemy.sql import Select

from storage_postgresql.schema import AnalysisEntry, FileObjectEntry, FirmwareEntry

FIRMWARE_ORDER = FirmwareEntry.vendor.asc(), FirmwareEntry.device_name.asc()


def build_generic_search_query(search_dict: dict, only_fo_parent_firmware: bool, inverted: bool) -> Select:
    if search_dict == {}:
        return select(FirmwareEntry).order_by(*FIRMWARE_ORDER)

    if only_fo_parent_firmware:
        return query_parent_firmware(search_dict, inverted)

    return build_query_from_dict(search_dict).order_by(FileObjectEntry.file_name.asc())


def query_parent_firmware(search_dict: dict, inverted: bool, count: bool = False) -> Select:
    # define alias so that FileObjectEntry can be referenced twice in query
    root_fo = aliased(FileObjectEntry, name='root_fo')
    base_query = (
        select(root_fo.uid)
        # explicitly state FROM because FileObjectEntry is not in select
        .select_from(root_fo, FileObjectEntry)
        # root_fo is in parent_firmware of the FO or FO is the "root file object" of the root_fo
        .filter(FileObjectEntry.root_firmware.any(uid=root_fo.uid) | (FileObjectEntry.uid == root_fo.uid))
    )
    query = build_query_from_dict(search_dict, query=base_query)

    if inverted:
        query_filter = FirmwareEntry.uid.notin_(query)
    else:
        query_filter = FirmwareEntry.uid.in_(query)

    if count:
        return select(func.count(FirmwareEntry.uid)).filter(query_filter)
    return select(FirmwareEntry).filter(query_filter).order_by(*FIRMWARE_ORDER)


def build_query_from_dict(query_dict: dict, query: Optional[Select] = None) -> Select:
    '''
    Builds an ``sqlalchemy.orm.Query`` object from a query in dict form.
    '''
    if query is None:
        query = select(FileObjectEntry)

    analysis_keys = [key for key in query_dict if key.startswith('processed_analysis')]
    if analysis_keys:
        query = _add_analysis_filter_to_query(analysis_keys, query, query_dict)

    firmware_keys = [key for key in query_dict if not key == 'uid' and hasattr(FirmwareEntry, key)]
    if firmware_keys:
        query = query.join(FirmwareEntry, FirmwareEntry.uid == FileObjectEntry.uid)
        for key in firmware_keys:
            query = query.filter(getattr(FirmwareEntry, key) == query_dict[key])

    file_object_keys = [key for key in query_dict if hasattr(FileObjectEntry, key)]
    if file_object_keys:
        for key in (key for key in query_dict if hasattr(FileObjectEntry, key)):
            query = query.filter(getattr(FileObjectEntry, key) == query_dict[key])

    return query


def _add_analysis_filter_to_query(analysis_keys: List[str], query: Select, query_dict: dict) -> Select:
    query = query.join(AnalysisEntry, AnalysisEntry.uid == FileObjectEntry.uid)
    for key in analysis_keys:  # type: str
        _, plugin, json_key = key.split('.', maxsplit=3)  # FixMe? nested json
        if hasattr(AnalysisEntry, key):
            if json_key == 'summary':  # special case: array field -> contains()
                needle = query_dict[key] if isinstance(query_dict[key], list) else [query_dict[key]]
                query = query.filter(AnalysisEntry.summary.contains(needle), AnalysisEntry.plugin == plugin)
            else:
                query = query.filter(getattr(AnalysisEntry, key) == query_dict[key])
        else:  # no meta field, actual analysis result key
            # FixMe? add support for arrays, nested documents, other operators than "="/"$eq"
            query = query.filter(
                AnalysisEntry.result[json_key].astext == query_dict[key],
                AnalysisEntry.plugin == plugin
            )
    return query
