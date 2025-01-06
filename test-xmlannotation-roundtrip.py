import lxml.etree
from ome_types.model import OME, XMLAnnotation

values = [
    '{"foo":1,"bar:"this>other"}',
    '<outer xmlns="http://example.com/">  <inner>ABC</inner>  </outer>',
    '   \n  mixed<b> \n content\n  </b>  ',
    'hello <mis> </matched> world',
]

ome = OME()
for v in values:
    try:
        lxml.etree.fromstring(f"<Value>{v}</Value>")
    except lxml.etree.XMLSyntaxError:
        v = XMLAnnotation.Value(any_elements=[v])
    ome.structured_annotations.append(XMLAnnotation(value=v))

def get_xmlannotation_value(a):
    e = lxml.etree.fromstring(a.value.to_xml(include_namespace=True, include_schema_location=False))
    print(a.value.to_xml(include_namespace=True, include_schema_location=False))
    lxml.etree.cleanup_namespaces(e)
    return e.text + ''.join(lxml.etree.tostring(c, encoding=str) for c in e)

print(ome.to_xml())
print()

values2 = [get_xmlannotation_value(a) for a in ome.structured_annotations]
for i, (v, v2) in enumerate(zip(values, values2), 1):
    if v == v2:
        print(f"{i}: SUCCESS")
    else:
        print(f"{i}: FAILURE")
    print("before:", repr(v))
    print("after: ", repr(v2))
    print()
