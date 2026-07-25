# Standalone verification — run from LatexCoverLetter dir
import sys
sys.path.insert(0, r"D:\AI_Learnigns\LatexCoverLetter")

from app.docs import load_facts, render_template, create_document

# 1. Load facts
facts = load_facts()
print(f"1. Facts loaded: {len(facts)} top-level keys — {list(facts.keys())}")
print(f"   Roles: {len(facts.get('roles',[]))} — {[r['id'] for r in facts['roles']]}")
print(f"   Skills: expert={len(facts['skills']['expert'])}, proficient={len(facts['skills']['proficient'])}, familiar={len(facts['skills']['familiar'])}")

# 2. Render ATS-CV template
try:
    rendered = render_template("ats-cv", {"facts": facts})
    lines = rendered.split("\n")
    print(f"\n2. ATS-CV rendered: {len(lines)} lines, {len(rendered)} chars")
    # Quick sanity: should contain role titles
    for role in facts["roles"]:
        if role["title"] in rendered:
            print(f"   ✓ Found role: {role['title'][:50]}")
        else:
            print(f"   ✗ MISSING role: {role['title'][:50]}")
    # Save for inspection
    Path("workspace/test_ats_rendered.tex").write_text(rendered, encoding="utf-8")
    print("   Saved to workspace/test_ats_rendered.tex")
except Exception as e:
    print(f"\n2. ATS-CV render ERROR: {e}")

# 3. Render designed-cv
try:
    rendered = render_template("designed-cv", {"facts": facts})
    lines = rendered.split("\n")
    print(f"\n3. Designed-CV rendered: {len(lines)} lines, {len(rendered)} chars")
    for role in facts["roles"]:
        if role["title"] in rendered:
            print(f"   ✓ Found role: {role['title'][:50]}")
        else:
            print(f"   ✗ MISSING role: {role['title'][:50]}")
    Path("workspace/test_designed_rendered.tex").write_text(rendered, encoding="utf-8")
    print("   Saved to workspace/test_designed_rendered.tex")
except Exception as e:
    import traceback
    print(f"\n3. Designed-CV render ERROR: {e}")
    traceback.print_exc()

print("\n=== DONE ===")
