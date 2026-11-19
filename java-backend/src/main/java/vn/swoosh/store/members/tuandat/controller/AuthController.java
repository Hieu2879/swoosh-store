package vn.swoosh.store.members.tuandat.controller;

import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.util.ArrayList;
import java.util.HashMap;
import java.util.List;
import java.util.Map;
import java.util.concurrent.ConcurrentHashMap;
import vn.swoosh.store.CredentialService;
import vn.swoosh.store.SecurityService;
import vn.swoosh.store.StoreDatabase;
import vn.swoosh.store.StoreSupport;
import org.springframework.http.CacheControl;
import org.springframework.http.ResponseEntity;
import org.springframework.jdbc.core.JdbcTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api")
public class AuthController {
    private final JdbcTemplate db;
    private final SecurityService security;
    private final CredentialService credentials;
    private final StoreDatabase storeDatabase;
    private final Map<String, List<Long>> loginAttempts = new ConcurrentHashMap<>();

    public AuthController(JdbcTemplate db, SecurityService security, CredentialService credentials,
                          StoreDatabase storeDatabase) {
        this.db = db;
        this.security = security;
        this.credentials = credentials;
        this.storeDatabase = storeDatabase;
    }

    @GetMapping("/health")
    Map<String, Object> health() {
        return Map.of("status", storeDatabase.initialized() ? "ok" : "starting",
            "time", java.time.Instant.now().toString());
    }

    @GetMapping("/session")
    ResponseEntity<Map<String, Object>> session(HttpServletRequest request, HttpServletResponse response) {
        Map<String, Object> session = security.currentSession(request);
        if (session == null) return security.createSession(null, request, response);
        Map<String, Object> body = new HashMap<>();
        body.put("csrfToken", session.get("csrf_token"));
        body.put("user", session.get("user_id") == null ? null : security.sessionUser(session));
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body);
    }

    @PostMapping("/login")
    ResponseEntity<Map<String, Object>> login(@RequestBody Map<String, Object> data,
                                               HttpServletRequest request, HttpServletResponse response) {
        Map<String, Object> guest = security.currentSession(request);
        if (guest == null) StoreSupport.fail(403, "Phiên đăng nhập hết hạn. Hãy tải lại trang.");
        security.requireCsrf(guest, request);
        String ip = security.clientIp(request);
        List<Long> attempts = loginAttempts.compute(ip, (key, previous) -> {
            long now = System.nanoTime();
            List<Long> recent = previous == null ? new ArrayList<>() : new ArrayList<>(previous);
            recent.removeIf(value -> now - value > 300_000_000_000L);
            if (recent.size() < 11) recent.add(now);
            return recent;
        });
        if (attempts.size() > 10) StoreSupport.fail(429, "Bạn đã thử đăng nhập quá nhiều lần. Hãy chờ 5 phút.");

        String username = StoreSupport.text(data.get("username")).trim();
        Object rawPassword = data.get("password");
        if (!(rawPassword instanceof String) || username.length() > 40
                || StoreSupport.text(rawPassword).length() > 256) {
            StoreSupport.fail(400, "Tên đăng nhập hoặc mật khẩu không hợp lệ.");
        }
        String password = (String) rawPassword;
        List<Map<String, Object>> users = db.queryForList("""
            SELECT users.*,
                   CASE WHEN users.status='ACTIVE' THEN 1 ELSE 0 END AS active,
                   CASE WHEN roles.role_code='ADMIN' THEN 'admin'
                        WHEN roles.role_id IS NOT NULL THEN 'staff' END AS role,
                   roles.role_id
            FROM users
            OUTER APPLY (
              SELECT TOP (1) role.role_id,role.role_code
              FROM user_roles user_role JOIN roles role ON role.role_id=user_role.role_id
              WHERE user_role.user_id=users.user_id
              ORDER BY CASE WHEN role.role_code='ADMIN' THEN 0 ELSE 1 END,role.role_id
            ) roles
            WHERE users.username=?
            """, username);
        if (users.isEmpty() || StoreSupport.number(users.get(0).get("active")) == 0
                || !credentials.matches(password, StoreSupport.text(users.get(0).get("password_hash")))) {
            security.recordActivity(username.isBlank() ? "Không rõ" : username, "Đăng nhập thất bại", "auth", "", request);
            StoreSupport.fail(401, "Tên đăng nhập hoặc mật khẩu không đúng.");
        }

        Map<String, Object> user = users.get(0);
        db.update("DELETE FROM app_sessions WHERE token_hash=?", guest.get("token_hash"));
        Map<String, Object> created = security.createSession(StoreSupport.number(user.get("user_id")), request, response).getBody();
        security.recordActivity(username, "Đăng nhập", "auth", "", request);
        loginAttempts.remove(ip);
        Map<String, Object> body = new HashMap<>(created);
        body.put("user", security.sessionUser(user));
        return ResponseEntity.ok().cacheControl(CacheControl.noStore()).body(body);
    }

    @PostMapping("/logout")
    Map<String, Object> logout(HttpServletRequest request, HttpServletResponse response) {
        Map<String, Object> session = security.currentSession(request);
        if (session == null) StoreSupport.fail(401, "Phiên đăng nhập đã hết hạn.");
        security.requireCsrf(session, request);
        db.update("DELETE FROM app_sessions WHERE token_hash=?", session.get("token_hash"));
        security.recordActivity(StoreSupport.text(session.get("username")), "Đăng xuất", "auth", "", request);
        security.expireCookie(request, response);
        return Map.of("ok", true);
    }
}
