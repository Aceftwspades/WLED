#include "wled.h"
#include "cube_fx_bank.h"

// ===========================================================================
// cube_fx_bank.cpp - the settings page for the effect slots
// ===========================================================================
// See cube_fx_bank.h for why the bank exists and how the roster is built. This
// file is the usermod around it: it loads the slot list from config, places the
// chosen effects in order during setup(), and renders the settings UI.
//
// ---------------------------------------------------------------------------
// WHY A SLOT LIST AND NOT A ROW OF CHECKBOXES
// ---------------------------------------------------------------------------
// Checkboxes would answer "which effects" in a third of the page weight. They
// cannot answer "in what order", and order is half the value here: registration
// order becomes effect-ID order, which becomes the order effects appear in the
// WLED list and in the on-cube menu. Left to the linker that order is
// unspecified and shifts between builds. A slot list makes it yours.
//
// ---------------------------------------------------------------------------
// THE PAGE IS HEAVY, ON PURPOSE
// ---------------------------------------------------------------------------
// CFX_BANK_SLOTS dropdowns each listing every compiled effect is on the order of
// a thousand addOption() calls streamed from the ESP32, so this page opens
// noticeably slower than the others. That is a deliberate trade: it is a page
// you visit when you change what ships, not one you live in. Everything else
// about the cube is unaffected - the cost is entirely in rendering this form.
// ===========================================================================

class CubeFxBankUsermod : public Usermod {
 private:
  bool     enabled = true;
  uint16_t slots[CFX_BANK_SLOTS] = {0};

  static const char _name[];

  // Slot keys are s00..s35 so they sort correctly in the JSON and in the form.
  static void slotKey(uint8_t i, char *out) {
    out[0] = 's'; out[1] = (char)('0' + (i / 10)); out[2] = (char)('0' + (i % 10)); out[3] = 0;
  }

 public:
  void setup() override {
    if (!enabled) {
      // Disabled means "get out of the way", not "register nothing" - a user who
      // switches the bank off wants the old behaviour back, not a dark cube.
      cfxBankConfigured() = false;
    }
    cfxBankApply();
  }

  void loop() override {}

  void addToConfig(JsonObject &root) override {
    JsonObject top = root.createNestedObject(FPSTR(_name));
    top[F("enabled")] = enabled;
    char k[4];
    for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) { slotKey(i, k); top[k] = slots[i]; }
  }

  bool readFromConfig(JsonObject &root) override {
    JsonObject top = root[FPSTR(_name)];
    if (top.isNull()) return false;

    getJsonValue(top[F("enabled")], enabled, true);
    char k[4];
    for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) {
      slotKey(i, k);
      uint16_t v = 0;
      getJsonValue(top[k], v, (uint16_t)0);
      slots[i] = v;
    }

    // Publish before any effect's setup() runs. WLED reads config in
    // deserializeConfigFromFS() and calls UsermodManager::setup() afterwards, so
    // this ordering is guaranteed by the boot sequence rather than by luck.
    for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) cfxBankSlots()[i] = slots[i];
    cfxBankConfigured() = enabled;
    return true;
  }

  void addToJsonInfo(JsonObject &root) override {
    JsonObject user = root[F("u")];
    if (user.isNull()) user = root.createNestedObject(F("u"));
    JsonArray s = user.createNestedArray(F("Cube FX slots"));
    char buf[48];
    if (!enabled) {
      snprintf_P(buf, sizeof(buf), PSTR("off - all %u registered"), (unsigned)cfxBankCount());
    } else {
      snprintf_P(buf, sizeof(buf), PSTR("%u of %u placed"),
                 (unsigned)cfxBankPlacedCount(), (unsigned)cfxBankCount());
    }
    s.add(buf);
    // Anything compiled but not placed is invisible in the effect list, and the
    // whole point of the bank is that this is a decision rather than a surprise.
    const uint8_t missing = (uint8_t)(cfxBankCount() - cfxBankPlacedCount());
    s.add(missing ? F(" - reboot to apply changes") : F(""));
  }

  void appendConfigData(Print &s) override {
    auto jsq = [&](const char *t) {
      for (const char *p = t; *p; ++p) { if (*p == '\'' || *p == '\\') s.print('\\'); s.print(*p); }
    };

    // --- the dropdowns -------------------------------------------------------
    // One per slot, each listing every compiled effect grouped by family. The
    // family is the name prefix, the same rule the on-cube menu groups by, so
    // the two stay in step without a second table to maintain.
    CfxBankEntry *r = cfxBankRoster();
    const uint8_t n = cfxBankCount();
    char nm[40], key[4];

    for (uint8_t i = 0; i < CFX_BANK_SLOTS; i++) {
      slotKey(i, key);
      s.print(F("dd=addDropdown('")); s.print(FPSTR(_name));
      s.print(F("','")); s.print(key); s.print(F("');"));
      s.print(F("addOption(dd,'-- empty --',0);"));
      for (uint8_t e = 0; e < n; e++) {
        cfxBankName(r[e].data, nm, sizeof(nm));
        s.print(F("addOption(dd,'")); jsq(nm); s.print(F("',")); s.print(r[e].hash); s.print(F(");"));
      }
    }

    // --- grey-out ------------------------------------------------------------
    // An effect chosen in one slot is disabled in the others, so two slots
    // cannot silently spend themselves on the same effect. Disabled rather than
    // hidden: options keep their positions, so the list does not reshuffle under
    // the cursor while you are working down it.
    //
    // The current slot's own value is never disabled, or reopening a select
    // would show it blank.
    s.print(F(
      "if(!window.cfxBankSync){window.cfxBankSync=function(){"
      "var f=document.getElementsByTagName('select'),u={},i,j,o;"
      "for(i=0;i<f.length;i++){if(f[i].name&&f[i].name.indexOf('CubeFXBank:s')==0){"
      "if(f[i].value!='0')u[f[i].value]=1;}}"
      "for(i=0;i<f.length;i++){if(f[i].name&&f[i].name.indexOf('CubeFXBank:s')==0){"
      "for(j=0;j<f[i].options.length;j++){o=f[i].options[j];"
      "o.disabled=(o.value!='0'&&u[o.value]&&o.value!=f[i].value);}}}"
      "var c=0;for(i=0;i<f.length;i++){if(f[i].name&&f[i].name.indexOf('CubeFXBank:s')==0&&f[i].value!='0')c++;}"
      "var t=document.getElementById('cfxBankCount');if(t)t.innerHTML=c+' of ' + f.length;"
      "};"
      "document.addEventListener('change',function(e){"
      "if(e.target&&e.target.name&&e.target.name.indexOf('CubeFXBank:s')==0)window.cfxBankSync();});"
      "setTimeout(window.cfxBankSync,300);}"));

    auto info = [&](const char *k, const char *html) {
      s.print(F("addInfo('")); s.print(FPSTR(_name)); s.print(F(":")); s.print(k);
      s.print(F("',1,'")); jsq(html); s.print(F("');"));
    };
    // All guidance rides on the ENABLED field, which is above the slot list.
    // Anchoring it to a slot instead puts the text after that slot's row - which
    // is the afterend behaviour of addInfo - and splits the list in two.
    info("enabled",
         "ticked, the slots below choose which effects appear and in what order - "
         "<b>on reboot</b>. An effect used in another slot is greyed out; leave a slot "
         "empty to keep it free. Untick to ignore the slots and register every "
         "compiled effect, as before the bank existed.");
  }

  uint16_t getId() override { return USERMOD_ID_UNSPECIFIED; }
};

const char CubeFxBankUsermod::_name[] PROGMEM = "CubeFXBank";

static CubeFxBankUsermod cube_fx_bank;
REGISTER_USERMOD(cube_fx_bank);
