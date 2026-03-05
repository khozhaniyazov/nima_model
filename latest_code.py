from manim import *


class GeneratedScene(Scene):
    def construct(self):
        def top_title(tex_str):
            t = MathTex(tex_str, font_size=40)
            t.to_edge(UP, buff=0.3)
            ul = Underline(t, buff=0.12).set_stroke(WHITE, 2).set_opacity(0.6)
            return VGroup(t, ul)

        def bottom_caption(tex_str, color=WHITE, font_size=30):
            cap = MathTex(tex_str, font_size=font_size, color=color)
            cap.to_edge(DOWN, buff=0.4)
            cap.set_opacity(0.95)
            return cap

        def subtle_plane(x_range=(-5, 5), y_range=(-3, 5)):
            plane = NumberPlane(
                x_range=[x_range[0], x_range[1], 1],
                y_range=[y_range[0], y_range[1], 1],
                background_line_style={"stroke_opacity": 0.15},
                faded_line_style={"stroke_opacity": 0.08},
                faded_line_ratio=3,
            ).set_opacity(0.3)
            return plane

        def make_axes():
            axes = Axes(
                x_range=[-3.5, 3.5, 1],
                y_range=[-1.5, 6.5, 1],
                x_length=10.0,
                y_length=5.6,
                axis_config={"color": BLUE_D, "stroke_width": 2},
                tips=False,
            ).add_coordinates(font_size=20)
            axes.to_edge(DOWN, buff=1.05)
            return axes

        DUR = {
            1: 17.2,
            2: 16.8,
            3: 15.0,
            4: 11.1,
            5: 11.6,
            6: 15.4,
            7: 12.0,
            8: 12.8,
            9: 11.1,
            10: 17.0,
            11: 18.7,
            12: 24.2,
        }

        # === SCENE 1 ===
        t1 = top_title(r"\text{First-order linear ODEs: } y' + y = e^x")
        title_center = MathTex(r"y' + y = e^x", font_size=76)
        title_center[0][0].set_color(YELLOW)
        title_center[0][4].set_color(GREEN)
        title_center[0][-1].set_color(BLUE)

        hook = MathTex(r"\text{A push toward }0\text{, plus a push upward}", font_size=32)
        hook.next_to(title_center, DOWN, buff=0.55)
        hook[0][4:13].set_color(GREEN)
        hook[0][16:22].set_color(BLUE)

        plane1 = subtle_plane(x_range=(-5, 5), y_range=(-3, 5))

        s1_time = 0.0
        self.play(FadeIn(t1, shift=UP * 0.2), run_time=1.1)
        s1_time += 1.1
        self.play(Create(plane1, lag_ratio=0.05), run_time=1.6)
        s1_time += 1.6
        self.play(Write(title_center), run_time=1.6)
        s1_time += 1.6
        self.play(FadeIn(hook, shift=UP * 0.15), run_time=1.0)
        s1_time += 1.0
        self.wait(2.0)
        s1_time += 2.0

        tug_left = Arrow(
            LEFT * 1.5,
            ORIGIN,
            buff=0,
            color=GREEN,
            stroke_width=6,
            max_tip_length_to_length_ratio=0.2,
        ).set_opacity(0.75)
        tug_up = Arrow(
            DOWN * 1.3,
            ORIGIN,
            buff=0,
            color=BLUE,
            stroke_width=6,
            max_tip_length_to_length_ratio=0.2,
        ).set_opacity(0.75)
        tug = VGroup(tug_left, tug_up).next_to(title_center, RIGHT, buff=1.0)
        tug_lbl = MathTex(r"\text{left: }-y,\ \text{up: }e^x", font_size=28)
        tug_lbl.next_to(tug, DOWN, buff=0.25)
        tug_lbl[0][2:4].set_color(GREEN)
        tug_lbl[0][8:11].set_color(BLUE)

        self.play(
            LaggedStart(GrowArrow(tug_left), GrowArrow(tug_up), Write(tug_lbl), lag_ratio=0.2),
            run_time=1.8,
        )
        s1_time += 1.8
        self.wait(1.3)
        s1_time += 1.3
        self.play(FadeOut(tug), FadeOut(tug_lbl), run_time=0.9)
        s1_time += 0.9
        self.play(
            title_center.animate.scale(0.65).to_edge(UP, buff=1.25),
            FadeOut(hook, shift=DOWN * 0.1),
            run_time=1.4,
        )
        s1_time += 1.4

        if s1_time < DUR[1]:
            self.wait(DUR[1] - s1_time)

        # === SCENE 2 ===
        t2 = top_title(r"\text{Standard form}")
        s2_time = 0.0

        main_eq = MathTex(r"y' + y = e^x", font_size=50)
        main_eq.next_to(t2, DOWN, buff=0.55)
        main_eq[0][0].set_color(YELLOW)
        main_eq[0][4].set_color(GREEN)
        main_eq[0][-1].set_color(BLUE)

        std = MathTex(r"y' + P(x)\,y = Q(x)", font_size=46)
        std.next_to(main_eq, DOWN, buff=0.55)
        std[0][0].set_color(YELLOW)

        # FIX: VMobjectFromSVGPath has no tex_string; use MathTex.get_tex_string() safely
        std_tex = std.get_tex_string()
        p_pos = std_tex.find("P(x)")
        if p_pos != -1:
            std[0][p_pos : p_pos + len("P(x)")].set_color(GREEN)
        q_pos = std_tex.find("Q(x)")
        if q_pos != -1:
            std[0][q_pos : q_pos + len("Q(x)")].set_color(BLUE)

        try:
            std[0][-5].set_color(GREEN)
        except Exception:
            pass

        px_rect = SurroundingRectangle(std[0][2:7], buff=0.12).set_stroke(GREEN, 2)
        qx_rect = SurroundingRectangle(std[0][-4:], buff=0.12).set_stroke(BLUE, 2)

        labels = VGroup(
            MathTex(r"P(x)=1", font_size=40, color=GREEN),
            MathTex(r"Q(x)=e^x", font_size=40, color=BLUE),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        labels.to_edge(RIGHT, buff=0.7).shift(DOWN * 0.5)

        arrows = VGroup(
            Arrow(
                labels[0].get_left(),
                std.get_right() + LEFT * 0.5 + UP * 0.1,
                buff=0.1,
                color=GREEN,
                stroke_width=4,
                max_tip_length_to_length_ratio=0.2,
            ),
            Arrow(
                labels[1].get_left(),
                std.get_right() + LEFT * 0.5 + DOWN * 0.35,
                buff=0.1,
                color=BLUE,
                stroke_width=4,
                max_tip_length_to_length_ratio=0.2,
            ),
        )

        cap2 = bottom_caption(r"\text{Linear: }y\text{ and }y'\text{ appear only to the first power.}")

        self.play(FadeTransform(t1, t2), run_time=0.9)
        s2_time += 0.9
        self.play(Write(main_eq), run_time=1.2)
        s2_time += 1.2
        self.play(Write(std), run_time=1.4)
        s2_time += 1.4
        self.play(LaggedStart(Create(px_rect), Create(qx_rect), lag_ratio=0.2), run_time=1.2)
        s2_time += 1.2
        self.play(LaggedStart(Write(labels[0]), GrowArrow(arrows[0]), lag_ratio=0.2), run_time=1.2)
        s2_time += 1.2
        self.play(LaggedStart(Write(labels[1]), GrowArrow(arrows[1]), lag_ratio=0.2), run_time=1.2)
        s2_time += 1.2
        self.play(Write(cap2), run_time=1.1)
        s2_time += 1.1
        self.wait(2.0)
        s2_time += 2.0
        self.play(FadeOut(px_rect), FadeOut(qx_rect), run_time=0.6)
        s2_time += 0.6
        self.play(main_eq.animate.set_opacity(0.35), run_time=0.6)
        s2_time += 0.6
        self.wait(2.0)
        s2_time += 2.0

        if s2_time < DUR[2]:
            self.wait(DUR[2] - s2_time)

        # === SCENE 3 ===
        t3 = top_title(r"\text{Integrating factor idea}")
        s3_time = 0.0

        goal = MathTex(r"\text{Goal: make the left side a product derivative}", font_size=34)
        goal.to_edge(RIGHT, buff=0.55).shift(UP * 0.15)

        mu_step = MathTex(r"\mu(x)\,\big(y' + P(x)\,y\big)=\mu(x)\,Q(x)", font_size=44)
        mu_step.next_to(std, DOWN, buff=0.7)
        for i, ch in enumerate(mu_step[0]):
            if ch.get_tex_string() == r"\mu":
                mu_step[0][i : i + 2].set_color(TEAL)
        mu_rhs_rect = SurroundingRectangle(mu_step[0][-5:], buff=0.12).set_stroke(BLUE, 2).set_opacity(0.9)

        arr_goal = Arrow(
            goal.get_left(),
            mu_step.get_right() + LEFT * 0.4,
            buff=0.15,
            color=WHITE,
            stroke_width=3,
            max_tip_length_to_length_ratio=0.15,
        ).set_opacity(0.85)

        prod_rule = MathTex(r"\frac{d}{dx}\big(\mu y\big)=\mu y' + \mu' y", font_size=42)
        prod_rule.to_edge(LEFT, buff=0.8).shift(UP * 0.2)
        prod_rule[0][0:6].set_color(TEAL)
        prod_rule[0][7:9].set_color(TEAL)
        prod_rule[0][12:14].set_color(TEAL)
        prod_rule[0][16:19].set_color(TEAL)

        cap3 = bottom_caption(
            r"\text{Choose }\mu\text{ so that }\mu'=\mu P(x)\text{ (then it matches product rule).}",
            font_size=30,
        )
        cap3[0][8:10].set_color(TEAL)

        self.play(FadeTransform(t2, t3), run_time=0.9)
        s3_time += 0.9
        self.play(LaggedStart(Write(goal), GrowArrow(arr_goal), lag_ratio=0.25), run_time=1.3)
        s3_time += 1.3
        self.play(Write(mu_step), run_time=1.6)
        s3_time += 1.6
        self.play(Create(mu_rhs_rect), run_time=0.8)
        s3_time += 0.8
        self.play(Write(prod_rule), run_time=1.7)
        s3_time += 1.7
        self.play(Write(cap3), run_time=1.2)
        s3_time += 1.2
        self.wait(2.2)
        s3_time += 2.2

        match = MathTex(r"\mu'=\mu P(x)", font_size=46)
        match.next_to(mu_step, DOWN, buff=0.55)
        match[0][0:2].set_color(TEAL)
        match[0][3:5].set_color(TEAL)
        match[0][5:9].set_color(GREEN)
        self.play(Write(match), run_time=1.2)
        s3_time += 1.2
        self.wait(1.8)
        s3_time += 1.8

        if s3_time < DUR[3]:
            self.wait(DUR[3] - s3_time)

        # === SCENE 4 ===
        t4 = top_title(r"\text{Find }\mu(x)")
        s4_time = 0.0

        mu_def = MathTex(r"\mu(x)=e^{\int P(x)\,dx}", font_size=52)
        mu_def.next_to(prod_rule, DOWN, buff=0.7).shift(RIGHT * 0.1)
        mu_def[0][0:2].set_color(TEAL)
        mu_def[0][3].set_color(BLUE)
        mu_def[0][5:8].set_color(GREEN)

        mu_eval1 = MathTex(r"\mu(x)=e^{\int 1\,dx}", font_size=52)
        mu_eval1.move_to(mu_def)
        mu_eval1[0][0:2].set_color(TEAL)
        mu_eval1[0][3].set_color(BLUE)

        mu_eval2 = MathTex(r"\mu(x)=e^{x}", font_size=52)
        mu_eval2.move_to(mu_def)
        mu_eval2[0][0:2].set_color(TEAL)
        mu_eval2[0][3].set_color(BLUE)

        mu_box = SurroundingRectangle(mu_eval2[0][3:], buff=0.14).set_stroke(BLUE, 2)
        cap4 = bottom_caption(r"P(x)=1\ \Rightarrow\ \mu(x)=e^x", font_size=32)
        cap4[0][0:4].set_color(GREEN)
        cap4[0][-2:].set_color(BLUE)

        self.play(FadeTransform(t3, t4), run_time=0.8)
        s4_time += 0.8
        self.play(Write(mu_def), run_time=1.4)
        s4_time += 1.4
        self.wait(0.7)
        s4_time += 0.7
        self.play(TransformMatchingTex(mu_def, mu_eval1), run_time=1.2)
        s4_time += 1.2
        self.play(TransformMatchingTex(mu_eval1, mu_eval2), run_time=1.2)
        s4_time += 1.2
        self.play(Create(mu_box), run_time=0.6)
        s4_time += 0.6
        self.play(Indicate(mu_eval2[0][3:], color=BLUE, scale_factor=1.06), run_time=0.7)
        s4_time += 0.7
        self.play(Write(cap4), run_time=1.0)
        s4_time += 1.0
        self.wait(3.5)
        s4_time += 3.5

        if s4_time < DUR[4]:
            self.wait(DUR[4] - s4_time)

        # === SCENE 5 ===
        t5 = top_title(r"\text{Multiply the whole equation by }e^x")
        s5_time = 0.0

        orig_faint = MathTex(r"y' + y = e^x", font_size=48).next_to(t5, DOWN, buff=0.55)
        orig_faint[0][0].set_color(YELLOW)
        orig_faint[0][4].set_color(GREEN)
        orig_faint[0][-1].set_color(BLUE)
        orig_faint.set_opacity(0.35)

        mult1 = MathTex(r"e^x y' + e^x y = e^x\cdot e^x", font_size=48)
        mult1.next_to(orig_faint, DOWN, buff=0.55)
        mult1[0][0:3].set_color(BLUE)
        mult1[0][4].set_color(YELLOW)
        mult1[0][8:11].set_color(BLUE)
        mult1[0][12].set_color(GREEN)
        mult1[0][-3:].set_color(BLUE)

        mult2 = MathTex(r"e^x y' + e^x y = e^{2x}", font_size=52)
        mult2.move_to(mult1)
        mult2[0][0:3].set_color(BLUE)
        mult2[0][4].set_color(YELLOW)
        mult2[0][8:11].set_color(BLUE)
        mult2[0][12].set_color(GREEN)
        mult2[0][-4:].set_color(BLUE)

        cap5 = bottom_caption(
            r"\text{Now the left side is ready to become } \frac{d}{dx}(e^x y).", font_size=30
        )
        cap5[0][33:39].set_color(BLUE)

        self.play(FadeTransform(t4, t5), run_time=0.9)
        s5_time += 0.9
        self.play(FadeOut(goal), FadeOut(arr_goal), FadeOut(mu_rhs_rect), run_time=0.6)
        s5_time += 0.6
        self.play(FadeIn(orig_faint), run_time=0.7)
        s5_time += 0.7
        self.play(Write(mult1), run_time=1.6)
        s5_time += 1.6
        self.wait(0.8)
        s5_time += 0.8
        self.play(TransformMatchingTex(mult1, mult2), run_time=1.2)
        s5_time += 1.2
        self.play(Write(cap5), run_time=1.0)
        s5_time += 1.0
        self.wait(4.8)
        s5_time += 4.8

        if s5_time < DUR[5]:
            self.wait(DUR[5] - s5_time)

        # === SCENE 6 ===
        t6 = top_title(r"\text{Recognize a product derivative}")
        s6_time = 0.0

        identity = MathTex(r"\frac{d}{dx}(e^x y)=e^x y' + e^x y", font_size=46)
        identity.to_edge(RIGHT, buff=0.55).shift(UP * 0.1)
        identity[0][6:9].set_color(BLUE)
        identity[0][9].set_color(GREEN)
        for i, ch in enumerate(identity[0]):
            if ch.get_tex_string() == "e":
                identity[0][i : i + 3].set_color(BLUE)

        brace = Brace(mult2, DOWN, buff=0.12)
        brace_text = MathTex(r"\text{this matches } \frac{d}{dx}(e^x y)", font_size=32)
        brace_text.next_to(brace, DOWN, buff=0.18)
        brace_text[0][14:18].set_color(BLUE)
        brace_text[0][18].set_color(GREEN)

        compact = MathTex(r"\frac{d}{dx}(e^x y)=e^{2x}", font_size=56)
        compact.move_to(mult2)
        compact[0][6:9].set_color(BLUE)
        compact[0][9].set_color(GREEN)
        compact[0][-4:].set_color(BLUE)

        cap6 = bottom_caption(
            r"\text{The trick: choose }\mu\text{ so product rule collapses the left side.}", font_size=30
        )
        cap6[0][18:20].set_color(TEAL)

        self.play(FadeTransform(t5, t6), run_time=0.9)
        s6_time += 0.9
        self.play(LaggedStart(Create(brace), Write(brace_text), lag_ratio=0.25), run_time=1.2)
        s6_time += 1.2
        self.play(Write(identity), run_time=1.6)
        s6_time += 1.6
        self.wait(1.2)
        s6_time += 1.2
        self.play(FadeOut(brace), FadeOut(brace_text), mult2.animate.set_opacity(0.4), run_time=0.8)
        s6_time += 0.8
        self.play(TransformMatchingTex(mult2, compact), run_time=1.5)
        s6_time += 1.5
        self.play(FadeOut(identity, shift=RIGHT * 0.2), run_time=0.8)
        s6_time += 0.8
        self.play(Write(cap6), run_time=1.0)
        s6_time += 1.0
        self.wait(6.4)
        s6_time += 6.4

        if s6_time < DUR[6]:
            self.wait(DUR[6] - s6_time)

        # === SCENE 7 ===
        t7 = top_title(r"\text{Integrate both sides}")
        s7_time = 0.0

        integ1 = MathTex(
            r"\int \frac{d}{dx}(e^x y)\,dx = \int e^{2x}\,dx",
            font_size=46,
        )
        integ1.next_to(compact, DOWN, buff=0.65)
        integ1[0][8:11].set_color(BLUE)
        integ1[0][11].set_color(GREEN)
        integ1[0][-4:].set_color(BLUE)

        integ2 = MathTex(r"e^x y = \frac{1}{2}e^{2x} + C", font_size=56)
        integ2.move_to(integ1)
        integ2[0][0:3].set_color(BLUE)
        integ2[0][3].set_color(GREEN)
        integ2[0][9:12].set_color(BLUE)
        integ2[0][13].set_color(BLUE)
        integ2[0][-1].set_color(YELLOW)

        c_note = MathTex(r"\text{constant}", font_size=30)
        c_note.next_to(integ2[-1], RIGHT, buff=0.25).shift(UP * 0.05)
        c_arrow = Arrow(
            c_note.get_left(),
            integ2[-1].get_center(),
            buff=0.1,
            color=YELLOW,
            stroke_width=3,
            max_tip_length_to_length_ratio=0.2,
        )

        cap7 = bottom_caption(r"\int e^{2x}\,dx=\frac{1}{2}e^{2x}+C", font_size=32)
        cap7[0][0:1].set_color(BLUE)
        cap7[0][10:15].set_color(BLUE)

        self.play(FadeTransform(t6, t7), run_time=0.9)
        s7_time += 0.9
        self.play(Write(integ1), run_time=1.5)
        s7_time += 1.5
        self.wait(0.8)
        s7_time += 0.8
        self.play(TransformMatchingTex(integ1, integ2), run_time=1.6)
        s7_time += 1.6
        self.play(LaggedStart(Write(c_note), GrowArrow(c_arrow), lag_ratio=0.25), run_time=1.2)
        s7_time += 1.2
        self.play(Write(cap7), run_time=0.9)
        s7_time += 0.9
        self.wait(5.1)
        s7_time += 5.1

        if s7_time < DUR[7]:
            self.wait(DUR[7] - s7_time)

        # === SCENE 8 ===
        t8 = top_title(r"\text{Solve for }y\text{ (general solution)}")
        s8_time = 0.0

        gen = MathTex(r"y = \frac{1}{2}e^{x} + C e^{-x}", font_size=64)
        gen.next_to(t8, DOWN, buff=0.55)
        gen[0][0].set_color(GREEN)
        gen[0][6:9].set_color(BLUE)
        gen[0][10].set_color(YELLOW)
        gen[0][12].set_color(YELLOW)
        gen[0][13:16].set_color(BLUE)

        label_gen = MathTex(r"\text{General solution}", font_size=34)
        label_gen.next_to(gen, UP, buff=0.25)

        axes = make_axes()
        axes_labels = axes.get_axis_labels(x_label="x", y_label="y")
        axes_labels[0].set_opacity(0.9)
        axes_labels[1].set_opacity(0.9)

        c = ValueTracker(0.0)
        c_display = DecimalNumber(0.0, num_decimal_places=2, font_size=32, color=YELLOW)
        c_display.add_updater(lambda m: m.set_value(c.get_value()))
        c_text = MathTex(r"C=", font_size=32, color=YELLOW)
        c_group = VGroup(c_text, c_display).arrange(RIGHT, buff=0.15)
        c_group.to_corner(DR, buff=0.55)

        def y_func(x, C):
            return 0.5 * np.exp(x) + C * np.exp(-x)

        curve_live = always_redraw(
            lambda: axes.plot(
                lambda x: y_func(x, c.get_value()),
                x_range=[-3.2, 3.2],
                color=YELLOW,
                stroke_width=5,
            )
        )

        ref_Cs = [-2.0, 0.0, 2.0]
        ref_colors = [RED_C, WHITE, GREEN_C]
        ref_curves = VGroup(
            *[
                axes.plot(
                    lambda x, C=C: y_func(x, C),
                    x_range=[-3.2, 3.2],
                    color=col,
                    stroke_width=2.5,
                ).set_opacity(0.35 if C != 0 else 0.22)
                for C, col in zip(ref_Cs, ref_colors)
            ]
        )

        cap8 = bottom_caption(r"\text{Changing }C\text{ sweeps out a whole family of solutions.}", font_size=30)
        cap8[0][9].set_color(YELLOW)

        self.play(FadeTransform(t7, t8), run_time=0.9)
        s8_time += 0.9
        self.play(FadeOut(compact), FadeOut(integ2), FadeOut(c_note), FadeOut(c_arrow), FadeOut(cap7), run_time=0.7)
        s8_time += 0.7
        self.play(LaggedStart(Write(label_gen), Write(gen), lag_ratio=0.15), run_time=1.4)
        s8_time += 1.4
        self.play(LaggedStart(Create(axes), Write(axes_labels), lag_ratio=0.15), run_time=1.6)
        s8_time += 1.6
        self.play(Create(ref_curves), run_time=1.0)
        s8_time += 1.0
        self.play(LaggedStart(FadeIn(c_group), Create(curve_live), lag_ratio=0.2), run_time=1.2)
        s8_time += 1.2
        self.play(Write(cap8), run_time=0.9)
        s8_time += 0.9
        self.play(c.animate.set_value(2.0), run_time=1.8, rate_func=smooth)
        s8_time += 1.8
        self.play(c.animate.set_value(-2.0), run_time=1.8, rate_func=smooth)
        s8_time += 1.8
        self.play(c.animate.set_value(0.0), run_time=0.8, rate_func=smooth)
        s8_time += 0.8
        self.wait(0.6)
        s8_time += 0.6

        if s8_time < DUR[8]:
            self.wait(DUR[8] - s8_time)

        # === SCENE 9 ===
        t9 = top_title(r"\text{Use an initial condition}")
        s9_time = 0.0

        ex = MathTex(r"\text{Example: } y(0)=1", font_size=40)
        ex.to_edge(LEFT, buff=0.65).shift(UP * 0.1)

        sub1 = MathTex(r"1 = \frac{1}{2}e^{0} + C e^{0}", font_size=48)
        sub1.next_to(ex, DOWN, buff=0.55).align_to(ex, LEFT)

        sub2 = MathTex(r"1 = \frac{1}{2} + C", font_size=48)
        sub2.move_to(sub1).align_to(sub1, LEFT)

        sub3 = MathTex(r"C = \frac{1}{2}", font_size=54)
        sub3.move_to(sub1).align_to(sub1, LEFT)
        sub3[0][0].set_color(YELLOW)

        dot0 = Dot(axes.c2p(0, 1), color=YELLOW).set_z_index(6)
        dot0_label = MathTex(r"(0,1)", font_size=30, color=YELLOW).next_to(dot0, UL, buff=0.15)

        self.play(FadeTransform(t8, t9), run_time=0.9)
        s9_time += 0.9
        self.play(LaggedStart(Write(ex), FadeIn(dot0), Write(dot0_label), lag_ratio=0.2), run_time=1.4)
        s9_time += 1.4
        self.play(Write(sub1), run_time=1.5)
        s9_time += 1.5
        self.wait(0.6)
        s9_time += 0.6
        self.play(TransformMatchingTex(sub1, sub2), run_time=1.2)
        s9_time += 1.2
        self.play(TransformMatchingTex(sub2, sub3), run_time=1.2)
        s9_time += 1.2

        self.play(c.animate.set_value(0.5), run_time=1.3, rate_func=smooth)
        s9_time += 1.3
        self.play(
            ref_curves.animate.set_opacity(0.08),
            curve_live.animate.set_stroke(width=6).set_color(YELLOW),
            run_time=1.1,
        )
        s9_time += 1.1
        self.wait(1.9)
        s9_time += 1.9

        if s9_time < DUR[9]:
            self.wait(DUR[9] - s9_time)

        # === SCENE 10 ===
        t10 = top_title(r"\text{Particular solution: growing + decaying}")
        s10_time = 0.0

        particular = MathTex(r"y=\frac{1}{2}e^{x}+\frac{1}{2}e^{-x}", font_size=62)
        particular.next_to(t10, DOWN, buff=0.55)
        particular[0][0].set_color(GREEN)
        particular[0][5:8].set_color(BLUE)
        particular[0][11:14].set_color(BLUE)

        grow = axes.plot(lambda x: 0.5 * np.exp(x), x_range=[-3.2, 3.2], color=BLUE_B, stroke_width=3).set_opacity(
            0.35
        )
        decay = axes.plot(
            lambda x: 0.5 * np.exp(-x), x_range=[-3.2, 3.2], color=PURPLE_B, stroke_width=3
        ).set_opacity(0.35)
        grow_d = DashedVMobject(grow, num_dashes=42)
        decay_d = DashedVMobject(decay, num_dashes=42)

        sum_label = MathTex(r"\text{sum}", font_size=28, color=YELLOW)
        sum_label.next_to(curve_live, UP, buff=0.15).shift(RIGHT * 2.2)

        brace_g = Brace(grow_d, RIGHT, buff=0.1)
        g_txt = MathTex(r"\text{growing part}", font_size=28, color=BLUE_B)
        g_txt.next_to(brace_g, RIGHT, buff=0.2)

        brace_d = Brace(decay_d, RIGHT, buff=0.1)
        d_txt = MathTex(r"\text{decaying part}", font_size=28, color=PURPLE_B)
        d_txt.next_to(brace_d, RIGHT, buff=0.2)

        cap10 = bottom_caption(
            r"\text{As }x\to\infty,\ e^{-x}\to 0\ \Rightarrow\ y\approx \frac12 e^x.", font_size=30
        )
        cap10[0][9:12].set_color(BLUE)
        cap10[0][14:18].set_color(BLUE)

        self.play(FadeTransform(t9, t10), run_time=0.9)
        s10_time += 0.9
        self.play(FadeOut(ex), FadeOut(dot0_label), FadeOut(sub3), run_time=0.9)
        s10_time += 0.9
        self.play(Write(particular), run_time=1.4)
        s10_time += 1.4
        self.play(LaggedStart(Create(grow_d), Create(decay_d), lag_ratio=0.2), run_time=1.6)
        s10_time += 1.6
        self.play(LaggedStart(FadeIn(sum_label), Create(brace_g), Write(g_txt), lag_ratio=0.2), run_time=1.6)
        s10_time += 1.6
        self.play(LaggedStart(Create(brace_d), Write(d_txt), lag_ratio=0.2), run_time=1.3)
        s10_time += 1.3
        self.play(Write(cap10), run_time=1.1)
        s10_time += 1.1
        self.wait(1.0)
        s10_time += 1.0

        x_tr = ValueTracker(-2.5)
        moving_dot = always_redraw(
            lambda: Dot(
                axes.c2p(x_tr.get_value(), y_func(x_tr.get_value(), 0.5)),
                radius=0.06,
                color=YELLOW,
            ).set_z_index(7)
        )
        trail = TracedPath(
            moving_dot.get_center,
            stroke_color=YELLOW,
            stroke_width=3,
            dissipating_time=0.6,
            stroke_opacity=[0.0, 0.9, 0.0],
        )
        self.add(trail)
        self.play(FadeIn(moving_dot), run_time=0.4)
        s10_time += 0.4
        self.play(x_tr.animate.set_value(3.0), run_time=3.3, rate_func=linear)
        s10_time += 3.3
        self.wait(2.5)
        s10_time += 2.5

        if s10_time < DUR[10]:
            self.wait(DUR[10] - s10_time)

        # === SCENE 11 ===
        t11 = top_title(r"\text{Verify by substitution}")
        s11_time = 0.0

        verify_top = MathTex(r"y' + y = e^x", font_size=52)
        verify_top.next_to(t11, DOWN, buff=0.55)
        verify_top[0][0].set_color(YELLOW)
        verify_top[0][4].set_color(GREEN)
        verify_top[0][-1].set_color(BLUE)

        y_line = MathTex(r"y=\frac12 e^x + C e^{-x}", font_size=44)
        yprime_line = MathTex(r"y'=\frac12 e^x - C e^{-x}", font_size=44)
        add_line = MathTex(
            r"y'+y=\left(\frac12 e^x - C e^{-x}\right)+\left(\frac12 e^x + C e^{-x}\right)",
            font_size=38,
        )
        simp_line = MathTex(r"y'+y=e^x", font_size=52)

        alg = VGroup(y_line, yprime_line, add_line, simp_line).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        alg.to_edge(LEFT, buff=0.65).shift(DOWN * 0.2)

        y_line[0][0].set_color(GREEN)
        y_line[0][5:8].set_color(BLUE)
        y_line[0][10].set_color(YELLOW)
        y_line[0][11:14].set_color(BLUE)

        yprime_line[0][0:2].set_color(YELLOW)
        yprime_line[0][6:9].set_color(BLUE)
        yprime_line[0][11].set_color(YELLOW)
        yprime_line[0][12:15].set_color(BLUE)

        simp_line[0][0:2].set_color(YELLOW)
        simp_line[0][3].set_color(GREEN)
        simp_line[0][5:8].set_color(BLUE)

        cancel_rect1 = SurroundingRectangle(add_line[0][9:14], buff=0.08).set_stroke(YELLOW, 2).set_opacity(0.9)
        cancel_rect2 = SurroundingRectangle(add_line[0][24:29], buff=0.08).set_stroke(YELLOW, 2).set_opacity(0.9)

        final_box = SurroundingRectangle(simp_line, buff=0.15).set_stroke(BLUE, 2.5)

        cap11 = bottom_caption(r"\text{The }Ce^{-x}\text{ terms cancel, leaving exactly }e^x.", font_size=30)
        cap11[0][4:10].set_color(YELLOW)
        cap11[0][32:35].set_color(BLUE)

        self.play(FadeTransform(t10, t11), run_time=0.9)
        s11_time += 0.9
        self.play(
            FadeOut(sum_label),
            FadeOut(brace_g),
            FadeOut(g_txt),
            FadeOut(brace_d),
            FadeOut(d_txt),
            FadeOut(cap10),
            FadeOut(moving_dot),
            run_time=1.0,
        )
        s11_time += 1.0
        self.play(Write(verify_top), run_time=1.1)
        s11_time += 1.1
        self.play(LaggedStart(Write(alg[0]), Write(alg[1]), lag_ratio=0.25), run_time=2.0)
        s11_time += 2.0
        self.play(Write(alg[2]), run_time=2.2)
        s11_time += 2.2
        self.play(LaggedStart(Create(cancel_rect1), Create(cancel_rect2), lag_ratio=0.2), run_time=1.0)
        s11_time += 1.0
        self.play(FadeOut(cancel_rect1), FadeOut(cancel_rect2), run_time=0.6)
        s11_time += 0.6
        self.play(TransformMatchingTex(alg[2].copy(), alg[3]), run_time=1.5)
        s11_time += 1.5
        self.play(Create(final_box), run_time=0.7)
        s11_time += 0.7
        self.play(Write(cap11), run_time=1.0)
        s11_time += 1.0
        self.wait(7.7)
        s11_time += 7.7

        if s11_time < DUR[11]:
            self.wait(DUR[11] - s11_time)

        # === SCENE 12 ===
        t12 = top_title(r"\text{Takeaway: the integrating factor workflow}")
        s12_time = 0.0

        self.play(FadeTransform(t11, t12), run_time=0.9)
        s12_time += 0.9
        self.play(
            FadeOut(verify_top),
            FadeOut(alg),
            FadeOut(simp_line),
            FadeOut(final_box),
            FadeOut(cap11),
            FadeOut(particular),
            run_time=1.3,
        )
        s12_time += 1.3

        panel_bg = RoundedRectangle(corner_radius=0.25, width=8.8, height=4.8)
        panel_bg.set_fill(color=BLACK, opacity=0.55).set_stroke(WHITE, 1.2, opacity=0.35)
        panel_bg.to_edge(LEFT, buff=0.6).shift(UP * 0.2)

        steps = VGroup(
            MathTex(r"1)\ \ y' + P(x)y = Q(x)", font_size=40),
            MathTex(r"2)\ \ \mu(x)=e^{\int P(x)\,dx}", font_size=40),
            MathTex(r"3)\ \ \frac{d}{dx}\big(\mu y\big)=\mu Q(x)", font_size=40),
            MathTex(r"4)\ \ y=\frac12 e^x + C e^{-x}", font_size=40),
        ).arrange(DOWN, aligned_edge=LEFT, buff=0.35)
        steps.move_to(panel_bg.get_center())

        steps[0][0][6:10].set_color(GREEN)
        steps[0][0][-4:].set_color(BLUE)
        steps[1][0][4:6].set_color(TEAL)
        steps[1][0][-6:-2].set_color(GREEN)
        steps[2][0][8:10].set_color(TEAL)
        steps[2][0][-4:].set_color(BLUE)
        steps[3][0][6:9].set_color(BLUE)
        steps[3][0][10].set_color(YELLOW)
        steps[3][0][11:14].set_color(BLUE)

        cap12 = bottom_caption(
            r"\text{For }y'+y=e^x:\ \ \mu=e^x,\ \ \Rightarrow\ y=\frac12 e^x + C e^{-x}.",
            font_size=30,
        )
        cap12[0][3:7].set_color(GREEN)
        cap12[0][10:13].set_color(BLUE)
        cap12[0][-10:-7].set_color(BLUE)

        self.play(FadeIn(panel_bg), run_time=0.7)
        s12_time += 0.7
        self.play(LaggedStart(*[Write(step) for step in steps], lag_ratio=0.18), run_time=2.8)
        s12_time += 2.8
        self.play(Write(cap12), run_time=1.2)
        s12_time += 1.2
        self.wait(1.0)
        s12_time += 1.0

        self.play(c.animate.set_value(1.2), run_time=2.3, rate_func=smooth)
        s12_time += 2.3
        self.play(c.animate.set_value(0.5), run_time=1.6, rate_func=smooth)
        s12_time += 1.6
        self.wait(1.0)
        s12_time += 1.0

        final_solution = MathTex(r"y=\frac12 e^x + C e^{-x}", font_size=56)
        final_solution.to_edge(DOWN, buff=0.85).shift(RIGHT * 2.3)
        final_solution[0][0].set_color(GREEN)
        final_solution[0][5:8].set_color(BLUE)
        final_solution[0][10].set_color(YELLOW)
        final_solution[0][11:14].set_color(BLUE)

        self.play(FadeIn(final_solution, shift=UP * 0.2), run_time=1.2)
        s12_time += 1.2
        self.wait(2.0)
        s12_time += 2.0

        self.play(
            FadeOut(panel_bg, shift=LEFT * 0.1),
            FadeOut(steps, shift=LEFT * 0.1),
            FadeOut(cap12),
            FadeOut(ref_curves),
            FadeOut(grow_d),
            FadeOut(decay_d),
            FadeOut(dot0),
            FadeOut(c_group),
            FadeOut(axes_labels),
            run_time=2.4,
        )
        s12_time += 2.4
        self.wait(1.0)
        s12_time += 1.0

        self.play(axes.animate.set_opacity(0.25), curve_live.animate.set_opacity(0.85), run_time=1.6)
        s12_time += 1.6
        self.wait(4.0)
        s12_time += 4.0
        self.play(FadeOut(axes), FadeOut(curve_live), run_time=2.0)
        s12_time += 2.0
        self.wait(1.0)
        s12_time += 1.0

        if s12_time < DUR[12]:
            self.wait(DUR[12] - s12_time)