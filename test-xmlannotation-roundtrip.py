from ome_types.model import OME, XMLAnnotation
import re
import io
import xml.etree.cElementTree as ETree

values = [
    '{"foo":1,"bar:"this>other"}',
    '<svg xmlns="http://www.w3.org/2000/svg"><g><rect x="416.066" y="226.858"/></g></svg>',
    '   \n  mixed<b> \n content\n  </b> after ',
    'hello <mis> </matched> world\n \n',
    '''<ChannelThresholds>
          <RoiName>011</RoiName>
          <Bluethreshold>-1</Bluethreshold>
          <Greenthreshold>-1</Greenthreshold>
          <Yellowthreshold>-1</Yellowthreshold>
          <Redthreshold>-1</Redthreshold>
        </ChannelThresholds>''',
]

ome = OME()
for v in values:
    try:
        ETree.parse(io.StringIO(v))
    except ETree.ParseError:
        v = XMLAnnotation.Value(any_elements=[v])
    ome.structured_annotations.append(XMLAnnotation(value=v))

def get_xmlannotation_value(a):
    xml = a.to_xml()
    value_xml = re.search(
        r"<Value>.*</Value>(?=\s*</XMLAnnotation>\s*$)", xml, re.DOTALL
    ).group()
    elt = ETree.parse(io.StringIO(value_xml)).getroot()
    new_xml = elt.text + "".join(ETree.tostring(c, encoding="unicode") for c in elt)
    try:
        new_xml = ETree.tostring(
            ETree.parse(io.StringIO(new_xml)).getroot(), encoding="unicode"
        )
    except ETree.ParseError:
        pass
    return new_xml

print(ome.to_xml())
print()

values2 = [get_xmlannotation_value(a) for a in ome.structured_annotations]
for i, (v, v2) in enumerate(zip(values, values2), 1):
    if v == v2:
        print(f"{i}: SUCCESS")
    else:
        print(f"{i}: FAILURE")
    print(f"before:\n{v}")
    print(f"after:\n{v2}")
    print()
