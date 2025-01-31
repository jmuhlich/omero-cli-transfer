# Copyright (C) 2022 The Jackson Laboratory
# All rights reserved.
#
# Use is subject to license terms supplied in LICENSE.

import ezomero
from ome_types import to_xml
from typing import List, Tuple, Union
from omero.model import DatasetI, IObject, PlateI, WellI, WellSampleI, ImageI
from omero.model import RoiI, LineI, PointI, RectangleI, EllipseI, PolygonI
from omero.model import PolylineI, AffineTransformI, Shape as OShape, LengthI
from omero.model import LabelI
from omero.gateway import DatasetWrapper
from ome_types.model import TagAnnotation, MapAnnotation, FileAnnotation, ROI
from ome_types.model import CommentAnnotation, LongAnnotation
from ome_types.model import TimestampAnnotation, Annotation
from ome_types.model import Line, Point, Rectangle, Ellipse, Polygon, Shape
from ome_types.model import Polyline, Label, Project, Screen, Dataset, OME
from ome_types.model import Image, Plate, XMLAnnotation, AnnotationRef
from ome_types.model.simple_types import Marker
from ome_types._mixins._base_type import OMEType
from omero.gateway import TagAnnotationWrapper, MapAnnotationWrapper
from omero.gateway import CommentAnnotationWrapper, LongAnnotationWrapper
from omero.gateway import FileAnnotationWrapper, OriginalFileWrapper
from omero.gateway import TimestampAnnotationWrapper, XmlAnnotationWrapper
from omero.sys import Parameters
from omero.gateway import BlitzGateway
from omero.rtypes import rstring, RStringI, rint, rdouble, rbool
from ezomero import rois
from pathlib import Path
import xml.etree.cElementTree as ETree
import os
import copy
import re
import json
import io
import generate_xml


# FIXME Remove this once ome-types fixes this (#270).
import ome_types.units
ome_types.units.ureg._on_redefinition = "ignore"
ome_types.units.ureg.define("@alias point = pt")


def create_or_set_projects(pjs: List[Project], conn: BlitzGateway,
                           merge: bool) -> dict:
    pj_map = {}
    if not merge:
        pj_map = create_projects(pjs, conn)
    else:
        for pj in pjs:
            pj_id = find_project(pj, conn)
            if not pj_id:
                pj_id = ezomero.post_project(conn, pj.name, pj.description)
            pj_map[pj.id] = pj_id
    return pj_map


def create_projects(pjs: List[Project], conn: BlitzGateway) -> dict:
    pj_map = {}
    for pj in pjs:
        pj_id = ezomero.post_project(conn, pj.name, pj.description)
        pj_map[pj.id] = pj_id
    return pj_map


def find_project(pj: Project, conn: BlitzGateway) -> int:
    id = 0
    my_exp_id = conn.getUser().getId()
    for p in conn.getObjects("Project", opts={'owner': my_exp_id}):
        if p.getName() == pj.name:
            id = p.getId()
    return id


def create_or_set_screens(scrs: List[Screen], conn: BlitzGateway, merge: bool
                          ) -> dict:
    scr_map = {}
    if not merge:
        scr_map = create_screens(scrs, conn)
    else:
        for scr in scrs:
            scr_id = find_screen(scr, conn)
            if not scr_id:
                scr_id = ezomero.post_screen(conn, scr.name, scr.description)
            scr_map[scr.id] = scr_id
    return scr_map


def create_screens(scrs: List[Screen], conn: BlitzGateway) -> dict:
    scr_map = {}
    for scr in scrs:
        scr_id = ezomero.post_screen(conn, scr.name, scr.description)
        scr_map[scr.id] = scr_id
    return scr_map


def find_screen(sc: Screen, conn: BlitzGateway) -> int:
    id = 0
    my_exp_id = conn.getUser().getId()
    for s in conn.getObjects("Screen", opts={'owner': my_exp_id}):
        if s.getName() == sc.name:
            id = s.getId()
    return id


def create_or_set_datasets(dss: List[Dataset], pjs: List[Project],
                           conn: BlitzGateway, merge: bool) -> dict:
    ds_map = {}
    if not merge:
        ds_map = create_datasets(dss, conn)
    else:
        for ds in dss:
            ds_id = find_dataset(ds, pjs, conn)
            if not ds_id:
                dataset = DatasetWrapper(conn, DatasetI())
                dataset.setName(ds.name)
                if ds.description is not None:
                    dataset.setDescription(ds.description)
                dataset.save()
                ds_id = dataset.getId()
            ds_map[ds.id] = ds_id
    return ds_map


def create_datasets(dss: List[Dataset], conn: BlitzGateway) -> dict:
    """
    Currently doing it the non-ezomero way because ezomero always
    puts "orphan" Datasets in the user's default group
    """
    ds_map = {}
    for ds in dss:
        dataset = DatasetWrapper(conn, DatasetI())
        dataset.setName(ds.name)
        if ds.description is not None:
            dataset.setDescription(ds.description)
        dataset.save()
        ds_id = dataset.getId()
        ds_map[ds.id] = ds_id
    return ds_map


def find_dataset(ds: Dataset, pjs: List[Project], conn: BlitzGateway) -> int:
    id = 0
    my_exp_id = conn.getUser().getId()
    orphan = True
    for pj in pjs:
        for dsref in pj.dataset_refs:
            if dsref.id == ds.id:
                orphan = False
    if not orphan:
        for pj in pjs:
            for p in conn.getObjects("Project", opts={'owner': my_exp_id}):
                if p.getName() == pj.name:
                    for dsref in pj.dataset_refs:
                        if dsref.id == ds.id:
                            for ds_rem in p.listChildren():
                                if ds.name == ds_rem.getName():
                                    id = ds_rem.getId()
    else:
        for d in conn.getObjects("Dataset", opts={'owner': my_exp_id,
                                                  'orphaned': True}):
            if d.getName() == ds.name:
                id = d.getId()
    return id


def create_annotations(ans: List[Annotation], conn: BlitzGateway, hash: str,
                       folder: str, figure: bool, obj_map: dict, img_map: dict,
                       metadata: List[str]) -> dict:
    ann_map = {}
    for an in ans:
        if an.id in obj_map:
            continue
        if isinstance(an, TagAnnotation):
            tag_ann = TagAnnotationWrapper(conn)
            tag_ann.setValue(an.value)
            tag_ann.setDescription(an.description)
            tag_ann.setNs(an.namespace)
            tag_ann.save()
            ann_map[an.id] = tag_ann.getId()
        elif isinstance(an, MapAnnotation):
            map_ann = MapAnnotationWrapper(conn)
            key_value_data = []
            for v in an.value.ms:
                key_value_data.append([v.k, v.value])
            map_ann.setValue(key_value_data)
            map_ann.setDescription(an.description)
            map_ann.setNs(an.namespace)
            map_ann.save()
            ann_map[an.id] = map_ann.getId()
        elif isinstance(an, CommentAnnotation):
            comm_ann = CommentAnnotationWrapper(conn)
            comm_ann.setValue(an.value)
            comm_ann.setDescription(an.description)
            comm_ann.setNs(an.namespace)
            comm_ann.save()
            ann_map[an.id] = comm_ann.getId()
        elif isinstance(an, TimestampAnnotation):
            ts_ann = TimestampAnnotationWrapper(conn)
            ts_ann.setValue(an.value)
            ts_ann.setDescription(an.description)
            ts_ann.setNs(an.namespace)
            ts_ann.save()
            ann_map[an.id] = ts_ann.getId()
        elif isinstance(an, LongAnnotation):
            comm_ann = LongAnnotationWrapper(conn)
            comm_ann.setValue(an.value)
            comm_ann.setDescription(an.description)
            comm_ann.setNs(an.namespace)
            comm_ann.save()
            ann_map[an.id] = comm_ann.getId()
        elif isinstance(an, FileAnnotation):
            if an.namespace == "omero.web.figure.json":
                if not figure:
                    continue
                else:
                    update_figure_refs(an, ans, img_map, folder)
            original_file = create_original_file(an, ans, conn, folder)
            file_ann = FileAnnotationWrapper(conn)
            file_ann.setDescription(an.description)
            file_ann.setNs(an.namespace)
            file_ann.setFile(original_file)
            file_ann.save()
            ann_map[an.id] = file_ann.getId()
        elif isinstance(an, XMLAnnotation):
            if an.namespace == "openmicroscopy.org/cli/transfer":
                # pass if path, use if provenance metadata
                tree = ETree.fromstring(to_xml(an.value,
                                               canonicalize=True))
                is_metadata = False
                for el in tree:
                    if el.tag.rpartition('}')[2] == "CLITransferMetadata":
                        is_metadata = True
                if is_metadata:
                    map_ann = MapAnnotationWrapper(conn)
                    namespace = an.namespace
                    map_ann.setNs(namespace)
                    key_value_data = []
                    if not metadata:
                        key_value_data.append(['empty_metadata', "True"])
                    else:
                        key_value_data = parse_xml_metadata(an, metadata, hash)
                    map_ann.setValue(key_value_data)
                    map_ann.save()
                    ann_map[an.id] = map_ann.getId()
            else:
                xml_ann = XmlAnnotationWrapper(conn)
                xml_ann.setValue(get_xmlannotation_value(an))
                xml_ann.setDescription(an.description)
                xml_ann.setNs(an.namespace)
                xml_ann.save()
                ann_map[an.id] = xml_ann.getId()
    return ann_map


def get_xmlannotation_value(a):
    xml = a.to_xml()
    value_xml = re.search(
        r"<Value>.*</Value>(?=\s*</XMLAnnotation>\s*$)", xml, re.DOTALL
    ).group()
    value_xml = value_xml.replace(
        "<Value>",
        '<Value xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">',
    )
    elt = ETree.parse(io.StringIO(value_xml)).getroot()
    new_xml = elt.text + "".join(ETree.tostring(c, encoding="unicode") for c in elt)
    try:
        new_xml = ETree.tostring(
            ETree.parse(io.StringIO(new_xml)).getroot(), encoding="unicode"
        )
    except ETree.ParseError:
        pass
    return new_xml


def parse_xml_metadata(ann: XMLAnnotation,
                       metadata: List[str],
                       hash: str) -> List[List[str]]:
    kv_data = []
    tree = ETree.fromstring(to_xml(ann.value, canonicalize=True))
    for el in tree:
        if el.tag.rpartition('}')[2] == "CLITransferMetadata":
            for el2 in el:
                item = el2.tag.rpartition('}')[2]
                val = el2.text
                if item == "md5" and "md5" in metadata:
                    kv_data.append(['md5', hash])
                if item == "origin_image_id" and "img_id" in metadata:
                    kv_data.append([item, val])
                if item == "origin_plate_id" and "plate_id" in metadata:
                    kv_data.append([item, val])
                if item == "packing_timestamp" and "timestamp" in metadata:
                    kv_data.append([item, val])
                if item == "software" and "software" in metadata:
                    kv_data.append([item, val])
                if item == "version" and "version" in metadata:
                    kv_data.append([item, val])
                if item == "origin_hostname" and "hostname" in metadata:
                    kv_data.append([item, val])
                if item == "original_user" and "orig_user" in metadata:
                    kv_data.append([item, val])
                if item == "original_group" and "orig_group" in metadata:
                    kv_data.append([item, val])
                if item == "database_id" and "db_id" in metadata:
                    kv_data.append([item, val])
    return kv_data


def get_server_path(anrefs: List[AnnotationRef],
                    ans: List[Annotation]) -> Union[str, None]:
    fpath = None
    xml_ids = []
    for an in anrefs:
        for an_loop in ans:
            if an.id == an_loop.id:
                if isinstance(an_loop, XMLAnnotation):
                    xml_ids.append(an_loop.id)
                else:
                    continue
    for an_loop in ans:
        if an_loop.id in xml_ids:
            if not fpath:
                tree = ETree.fromstring(to_xml(an_loop.value,
                                               canonicalize=True))
                for el in tree:
                    if el.tag.rpartition('}')[2] == "CLITransferServerPath":
                        for el2 in el:
                            if el2.tag.rpartition('}')[2] == "Path":
                                fpath = el2.text
    return fpath


def update_figure_refs(ann: FileAnnotation, ans: List[Annotation],
                       img_map: dict, folder: str):
    curr_folder = str(Path('.').resolve())
    fpath = get_server_path(ann.annotation_refs, ans)
    if fpath:
        dest_path = str(os.path.join(curr_folder, folder,  '.', fpath))
        with open(dest_path, 'r') as file:
            filedata = file.read()
        for src_id, dest_id in img_map.items():
            clean_id = int(src_id.split(":")[-1])
            src_str = f"\"imageId\": {clean_id},"
            dest_str = f"\"imageId\": {dest_id},"
            filedata = filedata.replace(src_str, dest_str)
        for fig in re.finditer("\"imageId\": ([0-9]+),", filedata):
            if int(fig.group(1)) not in img_map.values():
                src_str = f"\"imageId\": {fig.group(1)},"
                dest_str = f"\"imageId\": {str(-1)},"
                filedata = filedata.replace(src_str, dest_str)
        with open(dest_path, 'w') as file:
            file.write(filedata)
    return


def create_original_file(ann: FileAnnotation, ans: List[Annotation],
                         conn: BlitzGateway, folder: str
                         ) -> OriginalFileWrapper:
    curr_folder = str(Path('.').resolve())
    fpath = get_server_path(ann.annotation_refs, ans)
    dest_path = str(os.path.join(curr_folder, folder,  '.', fpath))
    ofile = conn.createOriginalFileFromLocalFile(dest_path)
    return ofile


def create_plate_map(ome: OME, img_map: dict, conn: BlitzGateway
                     ) -> Tuple[dict, OME]:
    newome = copy.deepcopy(ome)
    plate_map = {}
    map_ref_ids = []
    for plate in ome.plates:
        ann_ids = [i.id for i in plate.annotation_refs]
        for ann in ome.structured_annotations:
            if (ann.id in ann_ids and
                    isinstance(ann, XMLAnnotation)):
                tree = ETree.fromstring(to_xml(ann.value,
                                               canonicalize=True))
                is_metadata = False
                for el in tree:
                    if el.tag.rpartition('}')[2] == "CLITransferMetadata":
                        is_metadata = True
                if not is_metadata:
                    newome.structured_annotations.remove(ann)
                    map_ref_ids.append(ann.id)
                    file_path = get_server_path(plate.annotation_refs,
                                                ome.structured_annotations)
                    annref = next(filter(lambda x: x.id == ann.id,
                                         plate.annotation_refs))
                    newplate = next(filter(lambda x: x.id == plate.id,
                                           newome.plates))
                    newplate.annotation_refs.remove(annref)
        q = conn.getQueryService()
        params = Parameters()
        if not file_path:
            raise ValueError(f"Plate ID {plate.id} does not have a \
                             XMLAnnotation with a file path!")
        path_query = str(file_path).strip('/')
        if path_query.endswith('mock_folder'):
            path_query = path_query.rstrip("mock_folder")
        params.map = {"cpath": rstring('%%%s%%' % path_query)}
        results = q.projection(
            "SELECT p.id FROM Plate p"
            " JOIN p.plateAcquisitions a"
            " JOIN a.wellSample w"
            " JOIN w.image i"
            " JOIN i.fileset fs"
            " JOIN fs.usedFiles u"
            " WHERE u.clientPath LIKE :cpath",
            params,
            conn.SERVICE_OPTS
            )
        all_plate_ids = list(set(sorted([r[0].val for r in results])))
        plate_ids = []
        for pl_id in all_plate_ids:
            anns = ezomero.get_map_annotation_ids(conn, "Plate", pl_id)
            if not anns:
                plate_ids.append(pl_id)
            else:
                is_annotated = False
                for ann in anns:
                    ann_content = conn.getObject("MapAnnotation", ann)
                    if ann_content.getNs() == \
                            'openmicroscopy.org/cli/transfer':
                        is_annotated = True
                if not is_annotated:
                    plate_ids.append(pl_id)
        if plate_ids:
            # plate was imported as plate
            plate_id = plate_ids[0]
        else:
            # plate was imported as images
            plate_id = create_plate_from_images(plate, img_map, conn)
        plate_map[plate.id] = plate_id
    for p in newome.plates:
        for ref in p.annotation_refs:
            if ref.id in map_ref_ids:
                p.annotation_refs.remove(ref)
    return plate_map, newome


def create_plate_from_images(plate: Plate, img_map: dict, conn: BlitzGateway
                             ) -> int:
    plateobj = PlateI()
    plateobj.name = RStringI(plate.name)
    plateobj = conn.getUpdateService().saveAndReturnObject(plateobj)
    plate_id = plateobj.getId().getValue()
    for well in plate.wells:
        img_ids = []
        for ws in well.well_samples:
            if ws.image_ref:
                for imgref in ws.image_ref:
                    img_ids.append(img_map[imgref[-1]])
        add_image_to_plate(img_ids, plate_id, well.column,
                           well.row, conn)
    return plate_id


def add_image_to_plate(image_ids: List[int], plate_id: int, column: int,
                       row: int, conn: BlitzGateway) -> bool:
    """
    Add the Images to a Plate, creating a new well at the specified column and
    row
    NB - This will fail if there is already a well at that point
    """
    update_service = conn.getUpdateService()

    well = WellI()
    well.plate = PlateI(plate_id, False)
    well.column = rint(column)
    well.row = rint(row)

    try:
        for image_id in image_ids:
            image = conn.getObject("Image", image_id)
            ws = WellSampleI()
            ws.image = ImageI(image.id, False)
            ws.well = well
            well.addWellSample(ws)
        update_service.saveObject(well)
    except Exception:
        return False
    return True


def create_shape(shape: Shape) -> OShape:
    if isinstance(shape, Point):
        sh = PointI()
        # textValue is defined on each omero.model.Shape subclass
        # separately rather than on Shape itself, so technically
        # we should duplicate this code in each case.
        if shape.text:
            sh.textValue = rstring(shape.text)
        sh.x = rdouble(shape.x)
        sh.y = rdouble(shape.y)
    elif isinstance(shape, Line):
        sh = LineI()
        if shape.text:
            sh.textValue = rstring(shape.text)
        if shape.marker_end:
            sh.markerEnd = rstring(shape.marker_end.value)
        if shape.marker_start:
            sh.markerStart = rstring(shape.markerStart.value)
        sh.x1 = rdouble(shape.x1)
        sh.x2 = rdouble(shape.x2)
        sh.y1 = rdouble(shape.y1)
        sh.y2 = rdouble(shape.y2)
    elif isinstance(shape, Rectangle):
        sh = RectangleI()
        if shape.text:
            sh.textValue = rstring(shape.text)
        sh.x = rdouble(shape.x)
        sh.y = rdouble(shape.y)
        sh.width = rdouble(shape.width)
        sh.height = rdouble(shape.height)
    elif isinstance(shape, Ellipse):
        sh = EllipseI()
        if shape.text:
            sh.textValue = rstring(shape.text)
        sh.x = rdouble(shape.x)
        sh.y = rdouble(shape.y)
        sh.radiusX = rdouble(shape.radius_x)
        sh.radiusY = rdouble(shape.radius_y)
    elif isinstance(shape, Polygon):
        sh = PolygonI()
        if shape.text:
            sh.textValue = rstring(shape.text)
        sh.points = rstring(shape.points)
    elif isinstance(shape, Polyline):
        sh = PolylineI()
        if shape.text:
            sh.textValue = rstring(shape.text)
        if shape.marker_end:
            sh.markerEnd = rstring(shape.marker_end.value)
        if shape.marker_start:
            sh.markerStart = rstring(shape.markerStart.value)
        sh.points = rstring(shape.points)
    elif isinstance(shape, Label):
        sh = LabelI()
        if shape.text:
            sh.textValue = rstring(shape.text)
        sh.x = rdouble(shape.x)
        sh.y = rdouble(shape.y)
    else:
        raise ValueError(f"Unhandled shape type: {type(shape).__name__}")
    if shape.fill_color:
        sh.fillColor = rint(shape.fill_color)
    if shape.fill_rule:
        sh.fillRule = rstring(shape.fill_rule)
    # fontFamily is deprecated.
    if shape.font_size:
        sh.fontSize = quantity_to_length(shape.font_size_quantity)
    if shape.font_style:
        sh.fontStyle = rstring(shape.font_style)
    if sh.locked is not None:
        sh.locked = rbool(shape.locked)
    if shape.stroke_color:
        sh.strokeColor = rint(shape.stroke_color)
    if shape.stroke_dash_array:
        sh.strokeDashArray = rstring(shape.stroke_dash_array)
    if shape.stroke_width:
        sh.strokeWidth = quantity_to_length(shape.stroke_width_quantity)
    if sh.theC is not None:
        sh.theC = rint(sh.the_C)
    if sh.theT is not None:
        sh.theT = rint(sh.the_T)
    if sh.theZ is not None:
        sh.theZ = rint(sh.the_Z)
    if shape.transform:
        t = AffineTransformI()
        t.a00 = rdouble(shape.transform.a00)
        t.a10 = rdouble(shape.transform.a10)
        t.a01 = rdouble(shape.transform.a01)
        t.a11 = rdouble(shape.transform.a11)
        t.a02 = rdouble(shape.transform.a02)
        t.a12 = rdouble(shape.transform.a12)
        sh.transform = t
    return sh


def quantity_to_length(q):
    return LengthI(q.m, str(q.u).upper().replace("_", ""))


def _int_to_rgba(omero_val: int) -> Tuple[int, int, int, int]:
    """ Helper function returning the color as an Integer in RGBA encoding """
    if omero_val < 0:
        omero_val = omero_val + (2**32)
    r = omero_val >> 24
    g = omero_val - (r << 24) >> 16
    b = omero_val - (r << 24) - (g << 16) >> 8
    a = omero_val - (r << 24) - (g << 16) - (b << 8)
    # a = a / 256.0
    return (r, g, b, a)


def create_rois(rois: List[ROI], imgs: List[Image], obj_map: dict,
                img_map: dict, conn: BlitzGateway):
    new_rois = []
    for img in imgs:
        for roiref in img.roi_refs:
            if roiref.id in obj_map:
                continue
            roi = roiref.ref
            r = RoiI()
            if roi.name:
                r.name = rstring(roi.name)
            if roi.description:
                r.description = rstring(roi.description)
            for annref in roi.annotation_refs:
                link_one_annotation(r, annref.ref, obj_map, conn)
            for shape in roi.union:
                s = create_shape(shape)
                r.addShape(s)
                for annref in shape.annotation_refs:
                    link_one_annotation(s, annref.ref, obj_map, conn)
            i = ImageI(img_map[img.id], False)
            r.setImage(i)
            new_rois.append(r)
    update_service = conn.getUpdateService()
    update_service.saveArray(new_rois)
    return


def link_datasets(ome: OME, obj_map: dict, conn: BlitzGateway):
    for proj in ome.projects:
        proj_id = obj_map[proj.id]
        proj_obj = conn.getObject("Project", proj_id)
        existing_ds = []
        for dataset in proj_obj.listChildren():
            existing_ds.append(dataset.getId())
        ds_ids = []
        for ds in proj.dataset_refs:
            ds_id = obj_map[ds.id]
            if ds_id not in existing_ds:
                ds_ids.append(ds_id)
        ezomero.link_datasets_to_project(conn, ds_ids, proj_id)
    return


def link_plates(ome: OME, obj_map: dict, conn: BlitzGateway):
    for screen in ome.screens:
        screen_id = obj_map[screen.id]
        scr_obj = conn.getObject("Screen", screen_id)
        existing_pl = []
        for pl in scr_obj.listChildren():
            existing_pl.append(pl.getId())
        pl_ids = []
        for pl in screen.plate_refs:
            pl_id = obj_map[pl.id]
            if pl_id not in existing_pl:
                pl_ids.append(pl_id)
        ezomero.link_plates_to_screen(conn, pl_ids, screen_id)
    return


def link_images(ome: OME, obj_map: dict, img_map: dict, conn: BlitzGateway):
    for ds in ome.datasets:
        ds_id = obj_map[ds.id]
        img_ids = []
        for img in ds.image_refs:
            try:
                img_id = img_map[img.id]
                img_ids.append(img_id)
            except KeyError:
                continue
        ezomero.link_images_to_dataset(conn, img_ids, ds_id)
    return


def link_annotations(ome: OME, obj_map: dict, img_map: dict, conn: BlitzGateway):
    for proj in ome.projects:
        proj_id = obj_map[proj.id]
        proj_obj = conn.getObject("Project", proj_id)
        for annref in proj.annotation_refs:
            link_one_annotation(proj_obj, annref.ref, obj_map, conn)
    for ds in ome.datasets:
        ds_id = obj_map[ds.id]
        ds_obj = conn.getObject("Dataset", ds_id)
        for annref in ds.annotation_refs:
            link_one_annotation(ds_obj, annref.ref, obj_map, conn)
    for img in ome.images:
        try:
            img_id = img_map[img.id]
            img_obj = conn.getObject("Image", img_id)
            for annref in img.annotation_refs:
                link_one_annotation(img_obj, annref.ref, obj_map, conn)
        except KeyError:
            continue
    for scr in ome.screens:
        scr_id = obj_map[scr.id]
        scr_obj = conn.getObject("Screen", scr_id)
        for annref in scr.annotation_refs:
            link_one_annotation(scr_obj, annref.ref, obj_map, conn)
    for pl in ome.plates:
        pl_id = obj_map[pl.id]
        pl_obj = conn.getObject("Plate", pl_id)
        for annref in pl.annotation_refs:
            link_one_annotation(pl_obj, annref.ref, obj_map, conn)
        for well in pl.wells:
            if len(well.annotation_refs) > 0:
                row, col = well.row, well.column
                well_id = ezomero.get_well_id(conn, pl_id, row, col)
                well_obj = conn.getObject("Well", well_id)
                for annref in well.annotation_refs:
                    link_one_annotation(well_obj, annref.ref, obj_map, conn)
    return


def link_one_annotation(obj: IObject, ann: Annotation, obj_map: dict,
                        conn: BlitzGateway):
    ann_id = obj_map[ann.id]
    ann_obj = conn.getObject("Annotation", ann_id)
    if ann_obj:
        if isinstance(obj, IObject):
            ann_obj = ann_obj._obj
        else:
            if ann_obj in obj.listAnnotations():
                return
        obj.linkAnnotation(ann_obj)


def omexml_id_to_int(xml_id):
    return int(xml_id.split(":")[-1])


def find_existing_objects(ome: OME, img_map: dict, conn: BlitzGateway):
    """Return map of objects that were already created by image import.

    Image file import may create a number of objects like ROIs and Annotations
    that also exist in the transfer xml file. This function finds these
    redundant objects and returns a dict that maps their old ids to new ids.

    """
    ome_imported = OME()
    for imported_img_id in img_map.values():
        img = conn.getObject("Image", imported_img_id)
        generate_xml.populate_image(img, ome_imported, conn, "", [], False)
    import_map = {}
    for roi in ome_imported.rois:
        imported_roi_id = roi.id
        roi.id = 0
        roi.annotation_refs = []
        for shape in roi.union:
            shape.id = 0
            shape.annotation_refs = []
        import_map[to_xml(roi, exclude_defaults=True)] = omexml_id_to_int(
            imported_roi_id
        )
    for ann in ome_imported.structured_annotations:
        imported_ann_id = ann.id
        ann.id = 0
        ann.annotation_refs = []
        import_map[to_xml(ann, exclude_defaults=True)] = omexml_id_to_int(
            imported_ann_id
        )

    obj_map = {}
    for roi in ome.rois:
        roi = copy.deepcopy(roi)
        roi_id = roi.id
        roi.id = 0
        roi.annotation_refs = []
        for shape in roi.union:
            shape.id = 0
            shape.annotation_refs = []
        roi_xml = to_xml(roi, exclude_defaults=True)
        if roi_xml in import_map:
            obj_map[roi_id] = import_map[roi_xml]
    for ann in ome.structured_annotations:
        ann = copy.deepcopy(ann)
        ann_id = ann.id
        ann.id = 0
        ann.annotation_refs = []
        ann_xml = to_xml(ann, exclude_defaults=True)
        if ann_xml in import_map:
            obj_map[ann_id] = import_map[ann_xml]

    return obj_map


def apply_pvcs(im_obj, pvcs, conn):
    """Apply PathViewer channel settings to im_obj."""
    comm_ann = CommentAnnotationWrapper(conn)
    comm_ann.setNs("glencoesoftware.com/pathviewer/channel/settings")
    comm_ann.setValue(pvcs)
    comm_ann.save()
    channel0 = im_obj.getChannels()[0]
    channel0.linkAnnotation(comm_ann)


def apply_rdef(im_obj, rdef, conn):
    """Apply RenderingDef settings to im_obj"""
    # Based on code from omero-cli-render's "set" command.
    settings = json.loads(rdef)
    cs = settings["c"]
    if len(cs) != im_obj.getSizeC():
        print(f"Wrong number of channels in renderingdef (old rdef {rdef['id']}, new image {im_obj.id})")
        return
    windows = [(c["start"], c["end"]) for c in cs]
    colors = [c["color"] for c in cs]
    names = {i: c["label"] for i, c in enumerate(cs, 1)}
    active_channels = [i for i, c in enumerate(cs, 1) if c["active"]]
    im_obj.set_active_channels(
        names.keys(), windows=windows, colors=colors, set_inactive=True
    )
    if settings["model"] == "rgb":
        im_obj.setColorRenderingModel()
    elif settings["model"] == "greyscale":
        im_obj.setGreyscaleRenderingModel()
    else:
        print(f"Unrecognized renderingdef model: {settings['model']}")
    im_obj.set_active_channels(active_channels)
    im_obj.setDefaultZ(settings["z"])
    im_obj.setDefaultT(settings["t"])
    im_obj.saveDefaults()
    conn.setChannelNames("Image", [im_obj.id], names)


def pop_annotation(ome: OME, obj: OMEType, namespace: str):
    """Remove and return obj's first annotation matching the given namespace

    Removes the annotation reference from obj and also removes the annotation
    itself from ome's list of annotations.

    """
    if not hasattr(obj, "annotation_refs"):
        raise ValueError("obj does not have an annotation_refs attribute")
    for r in obj.annotation_refs:
        if r.ref.namespace == namespace:
            # Avoid early gc of weakly-referenced annotation object.
            ann = r.ref
            ome.structured_annotations.remove(ann)
            obj.annotation_refs.remove(r)
            return ann
    else:
        return None


def apply_image_settings(ome: OME, img_map: dict, conn: BlitzGateway):
    for img in ome.images:
        img_id = img_map.get(img.id)
        if not img_id:
            print(f"Image corresponding to {img.id} not found. Skipping.")
            continue
        im_obj = conn.getObject("Image", img_id)
        pvcs_ann = pop_annotation(ome, img, "openmicroscopy.org/cli/transfer/pathviewer-channel-settings")
        rdef_ann = pop_annotation(ome, img, "openmicroscopy.org/cli/transfer/renderingdef")
        apply_pvcs(im_obj, pvcs_ann.value, conn)
        apply_rdef(im_obj, rdef_ann.value, conn)


def rename_images(imgs: List[Image], img_map: dict, conn: BlitzGateway):
    for img in imgs:
        try:
            img_id = img_map[img.id]
            im_obj = conn.getObject("Image", img_id)
            im_obj.setName(img.name)
            im_obj.save()
        except KeyError:
            print(f"Image corresponding to {img.id} not found. Skipping.")
    return


def rename_plates(pls: List[Plate], pl_map: dict, conn: BlitzGateway):
    for pl in pls:
        try:
            pl_id = pl_map[pl.id]
            pl_obj = conn.getObject("Plate", pl_id)
            pl_obj.setName(pl.name)
            pl_obj.save()
        except KeyError:
            print(f"Plate corresponding to {pl.id} not found. Skipping.")
    return


def populate_omero(ome: OME, img_map: dict, conn: BlitzGateway, hash: str,
                   folder: str, metadata: List[str], merge: bool,
                   figure: bool):
    obj_map = find_existing_objects(ome, img_map, conn)
    plate_map, ome = create_plate_map(ome, img_map, conn)
    apply_image_settings(ome, img_map, conn)
    rename_images(ome.images, img_map, conn)
    rename_plates(ome.plates, plate_map, conn)
    proj_map = create_or_set_projects(ome.projects, conn, merge)
    ds_map = create_or_set_datasets(ome.datasets, ome.projects, conn, merge)
    screen_map = create_or_set_screens(ome.screens, conn, merge)
    ann_map = create_annotations(ome.structured_annotations, conn, hash, folder,
                                 figure, obj_map, img_map, metadata)
    for m in plate_map, proj_map, ds_map, screen_map, ann_map:
        obj_map.update(m)
    create_rois(ome.rois, ome.images, obj_map, img_map, conn)
    link_plates(ome, obj_map, conn)
    link_datasets(ome, obj_map, conn)
    link_images(ome, obj_map, img_map, conn)
    link_annotations(ome, obj_map, img_map, conn)
    return
